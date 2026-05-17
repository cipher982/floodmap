#!/usr/bin/env python3
"""Run product-level QA against the real FloodMap map path."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageChops, ImageStat
from playwright.async_api import async_playwright

DEFAULT_PATH = "/al/birmingham?handGpu=1"
WATER_LEVELS = {
    "low": 0.5,
    "mid": 10.0,
    "high": 1000.0,
}


@dataclass(frozen=True)
class ProductQaResult:
    pass_: bool
    url: str
    screenshots: dict[str, str]
    stats_before: dict
    stats_after: dict
    metadata: dict
    visual_metrics: dict
    console_errors: list[str]
    page_errors: list[str]
    failed_requests: list[str]
    bad_responses: list[str]
    failures: list[str]

    def to_json(self) -> dict:
        return {
            "pass": self.pass_,
            "url": self.url,
            "screenshots": self.screenshots,
            "stats_before": self.stats_before,
            "stats_after": self.stats_after,
            "metadata": self.metadata,
            "visual_metrics": self.visual_metrics,
            "console_errors": self.console_errors,
            "page_errors": self.page_errors,
            "failed_requests": self.failed_requests,
            "bad_responses": self.bad_responses,
            "failures": self.failures,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=60000)
    return parser.parse_args()


def default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("docs/qa/flood-product/runs") / stamp


def browser_launch_args(base_url: str) -> list[str]:
    launch_args = [
        "--disable-dev-shm-usage",
        "--enable-unsafe-webgpu",
        "--enable-webgpu",
        "--ignore-gpu-blocklist",
    ]
    parsed = urlparse(base_url)
    origin = (
        f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    )
    if (
        parsed.scheme == "http"
        and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        and origin
    ):
        launch_args.append(f"--unsafely-treat-insecure-origin-as-secure={origin}")
    return launch_args


def build_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


async def wait_for_product_ready(page, timeout_ms: int) -> None:
    await page.wait_for_function(
        """
        () => {
          const fm = window.floodMap;
          if (!fm?.map || fm.viewMode !== 'hand') return false;
          if (!fm.map.loaded()) return false;
          const stats = fm.handGpuLayer?.getStats?.();
          return Boolean(stats?.active && stats?.tileTextureCount > 0 && stats?.textureUploads > 0);
        }
        """,
        timeout=timeout_ms,
    )


async def set_water_level(page, level: float, timeout_ms: int) -> None:
    await page.evaluate(
        """
        (level) => {
          const fm = window.floodMap;
          if (!fm) throw new Error('window.floodMap is unavailable');
          fm.currentWaterLevel = level;
          const slider = document.getElementById('water-level');
          if (slider && typeof fm.waterLevelToSlider === 'function') {
            slider.value = String(fm.waterLevelToSlider(level));
            slider.dispatchEvent(new Event('input', { bubbles: true }));
          } else {
            fm.syncWaterLevelControls?.();
            fm.updateFloodLayer?.();
            fm.schedulePermalinkUpdate?.();
          }
        }
        """,
        level,
    )
    await page.wait_for_function(
        "(level) => Math.abs((window.floodMap?.currentWaterLevel || 0) - level) < 0.11",
        level,
        timeout=timeout_ms,
    )
    await page.wait_for_timeout(450)


async def capture_map_screenshot(page, path: Path) -> None:
    await page.locator("#map").screenshot(path=str(path))


def image_change_metrics(a_path: Path, b_path: Path) -> dict[str, float]:
    with (
        Image.open(a_path).convert("RGB") as a_img,
        Image.open(b_path).convert("RGB") as b_img,
    ):
        if a_img.size != b_img.size:
            b_img = b_img.resize(a_img.size)
        diff = ImageChops.difference(a_img, b_img)
        stat = ImageStat.Stat(diff)
        mean_abs = sum(stat.mean) / len(stat.mean)
        changed = 0
        total = diff.size[0] * diff.size[1]
        for r, g, b in diff.getdata():
            if max(r, g, b) >= 18:
                changed += 1
        return {
            "mean_abs_rgb_delta": round(float(mean_abs), 3),
            "changed_pixel_ratio": round(changed / total, 5),
        }


def visual_richness_metrics(path: Path) -> dict[str, float | int]:
    with Image.open(path).convert("RGB") as img:
        sample = img.resize((240, max(1, int(240 * img.height / img.width))))
        colors = sample.getcolors(maxcolors=1_000_000) or []
        blueish = 0
        total = sample.size[0] * sample.size[1]
        for count, (r, g, b) in colors:
            if b > r + 20 and b >= g - 15:
                blueish += count
        return {
            "unique_sample_colors": len(colors),
            "blueish_pixel_ratio": round(blueish / total, 5),
        }


async def run_product_qa(args: argparse.Namespace, out_dir: Path) -> ProductQaResult:
    screenshots_dir = out_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    url = build_url(args.base_url, args.path)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    bad_responses: list[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=not args.headed,
            args=browser_launch_args(args.base_url),
        )
        page = await browser.new_page(
            viewport={"width": 1500, "height": 950}, device_scale_factor=1
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda msg: (
                console_errors.append(msg.text)
                if msg.type == "error" and "Cross-Origin-Opener-Policy" not in msg.text
                else None
            ),
        )
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.url} {request.failure.get('errorText') if request.failure else ''}"
            ),
        )
        page.on(
            "response",
            lambda response: (
                bad_responses.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None
            ),
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        await wait_for_product_ready(page, args.timeout_ms)
        await page.wait_for_timeout(500)
        stats_before = await page.evaluate(
            "() => window.floodMap.handGpuLayer.getStats()"
        )
        metadata = await page.evaluate(
            """
            async () => {
              const response = await fetch(window.floodmapApiUrl('/v2/terrain/hand/metadata'));
              return {
                ok: response.ok,
                status: response.status,
                body: await response.json()
              };
            }
            """
        )

        water_screenshots: dict[str, Path] = {}
        for label, level in WATER_LEVELS.items():
            await set_water_level(page, level, args.timeout_ms)
            shot_path = screenshots_dir / f"real-map-{label}-water.png"
            await capture_map_screenshot(page, shot_path)
            water_screenshots[label] = shot_path

        map_box = await page.locator("#map").bounding_box()
        if map_box:
            start_x = map_box["x"] + map_box["width"] * 0.55
            start_y = map_box["y"] + map_box["height"] * 0.52
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            await page.mouse.move(start_x - 180, start_y - 60, steps=12)
            await page.mouse.up()
        await page.wait_for_function(
            "() => window.floodMap?.map && !window.floodMap.map.isMoving()",
            timeout=args.timeout_ms,
        )
        await wait_for_product_ready(page, args.timeout_ms)
        render_count_before = await page.evaluate(
            "() => window.floodMap.handGpuLayer.getStats().renderCount"
        )
        await page.wait_for_timeout(850)
        stats_after = await page.evaluate(
            "() => window.floodMap.handGpuLayer.getStats()"
        )
        panned_path = screenshots_dir / "real-map-panned.png"
        await capture_map_screenshot(page, panned_path)

        share_url = await page.evaluate("() => window.floodMap.buildShareUrl()")
        share_page = await browser.new_page(
            viewport={"width": 1500, "height": 950}, device_scale_factor=1
        )
        share_page.on("pageerror", lambda error: page_errors.append(str(error)))
        share_page.on(
            "console",
            lambda msg: (
                console_errors.append(msg.text)
                if msg.type == "error" and "Cross-Origin-Opener-Policy" not in msg.text
                else None
            ),
        )
        share_page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.url} {request.failure.get('errorText') if request.failure else ''}"
            ),
        )
        share_page.on(
            "response",
            lambda response: (
                bad_responses.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None
            ),
        )
        await share_page.goto(
            share_url, wait_until="domcontentloaded", timeout=args.timeout_ms
        )
        await wait_for_product_ready(share_page, args.timeout_ms)
        share_state = await share_page.evaluate(
            """
            () => ({
              view: window.floodMap.viewMode,
              water: window.floodMap.currentWaterLevel,
              stats: window.floodMap.handGpuLayer.getStats()
            })
            """
        )
        await share_page.close()
        await browser.close()

    low_to_mid = image_change_metrics(
        water_screenshots["low"], water_screenshots["mid"]
    )
    mid_to_high = image_change_metrics(
        water_screenshots["mid"], water_screenshots["high"]
    )
    visual_metrics = {
        "low_to_mid": low_to_mid,
        "mid_to_high": mid_to_high,
        "high_richness": visual_richness_metrics(water_screenshots["high"]),
        "share_state": share_state,
    }

    failures: list[str] = []
    if console_errors:
        failures.append("console errors")
    if page_errors:
        failures.append("page errors")
    if failed_requests:
        failures.append("failed requests")
    if bad_responses:
        failures.append("HTTP 4xx/5xx responses")
    if not metadata.get("ok"):
        failures.append("HAND metadata request failed")
    if not metadata.get("body", {}).get("regions"):
        failures.append("HAND metadata has no regions")
    if not stats_after.get("active"):
        failures.append("HAND GPU layer inactive")
    if stats_after.get("visualModel") != "terrain-flow-streaks-v2":
        failures.append("terrain-flow-streak visual model not active")
    if stats_after.get("tileTextureCount", 0) <= 0:
        failures.append("no real HAND tile textures loaded")
    if stats_after.get("textureUploads", 0) <= 0:
        failures.append("no HAND texture uploads")
    if stats_after.get("renderCount", 0) <= render_count_before:
        failures.append("animated layer did not repaint")
    if low_to_mid["changed_pixel_ratio"] < 0.01:
        failures.append("low-to-mid slider change is not visually meaningful")
    if mid_to_high["changed_pixel_ratio"] < 0.01:
        failures.append("mid-to-high slider change is not visually meaningful")
    if visual_metrics["high_richness"]["unique_sample_colors"] < 256:
        failures.append("high-water map is too visually flat")
    if share_state.get("view") != "hand":
        failures.append("share URL did not preserve Flood Toy mode")
    if abs(float(share_state.get("water", -999)) - WATER_LEVELS["high"]) > 0.2:
        failures.append("share URL did not preserve water level")

    return ProductQaResult(
        pass_=not failures,
        url=url,
        screenshots={
            "low": str(water_screenshots["low"]),
            "mid": str(water_screenshots["mid"]),
            "high": str(water_screenshots["high"]),
            "panned": str(panned_path),
        },
        stats_before=stats_before,
        stats_after=stats_after,
        metadata=metadata,
        visual_metrics=visual_metrics,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        bad_responses=bad_responses,
        failures=failures,
    )


async def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = await run_product_qa(args, out_dir)
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        **result.to_json(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_markdown(out_dir / "summary.md", summary)
    print(json.dumps({"output_dir": str(out_dir), **summary}, indent=2))
    return 0 if result.pass_ else 1


def write_markdown(path: Path, summary: dict) -> None:
    regions = summary["metadata"].get("body", {}).get("regions", [])
    stats = summary["stats_after"]
    lines = [
        "# FloodMap Product QA",
        "",
        f"- Pass: `{summary['pass']}`",
        f"- URL: `{summary['url']}`",
        f"- Visual model: `{stats.get('visualModel')}`",
        f"- HAND textures: `{stats.get('tileTextureCount')}`",
        f"- Texture uploads: `{stats.get('textureUploads')}`",
        f"- Render count: `{stats.get('renderCount')}`",
        f"- Metadata regions: `{len(regions)}`",
        f"- Low-water screenshot: `{Path(summary['screenshots']['low']).name}`",
        f"- Mid-water screenshot: `{Path(summary['screenshots']['mid']).name}`",
        f"- High-water screenshot: `{Path(summary['screenshots']['high']).name}`",
        f"- Panned screenshot: `{Path(summary['screenshots']['panned']).name}`",
        f"- Low-to-mid changed pixels: `{summary['visual_metrics']['low_to_mid']['changed_pixel_ratio']}`",
        f"- Mid-to-high changed pixels: `{summary['visual_metrics']['mid_to_high']['changed_pixel_ratio']}`",
        f"- High-water sample colors: `{summary['visual_metrics']['high_richness']['unique_sample_colors']}`",
        "",
    ]
    if summary["failures"]:
        lines.append("## Failures")
        lines.extend(f"- {failure}" for failure in summary["failures"])
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

#!/usr/bin/env python3
"""Run product QA against the real 3D terrain FloodMap path."""

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

DEFAULT_PATH = "/terrain-3d?lat=33.5186&lng=-86.8104&zoom=12&water=28&exaggeration=2.0"


@dataclass(frozen=True)
class Terrain3dQaResult:
    pass_: bool
    url: str
    screenshots: dict[str, str]
    stats: dict
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
            "stats": self.stats,
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
    parser.add_argument("--timeout-ms", type=int, default=90000)
    return parser.parse_args()


def default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("docs/qa/terrain-3d/runs") / stamp


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
    if path.startswith(("http://", "https://")):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def add_query_param(url: str, param: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{param}"


async def wait_for_terrain_ready(page, timeout_ms: int) -> None:
    await page.wait_for_function(
        """
        () => {
          const app = window.floodTerrain3d;
          const stats = app?.stats;
          return Boolean(
            stats?.ready &&
            stats?.terrainLoaded &&
            stats?.handLoaded &&
            stats?.basemapCaptured &&
            stats?.waterVisible &&
            stats?.tileCount >= 9 &&
            stats?.tilesLoaded >= 9 &&
            stats?.frameCount > 8
          );
        }
        """,
        timeout=timeout_ms,
    )


def visual_richness_metrics(path: Path) -> dict[str, float | int]:
    with Image.open(path).convert("RGB") as img:
        sample = img.resize((260, max(1, int(260 * img.height / img.width))))
        colors = sample.getcolors(maxcolors=1_000_000) or []
        blueish = 0
        very_dark = 0
        total = sample.size[0] * sample.size[1]
        for count, (r, g, b) in colors:
            if b > r + 22 and b >= g - 12:
                blueish += count
            if r < 16 and g < 16 and b < 16:
                very_dark += count
        return {
            "unique_sample_colors": len(colors),
            "blueish_pixel_ratio": round(blueish / total, 5),
            "very_dark_pixel_ratio": round(very_dark / total, 5),
        }


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
            if max(r, g, b) >= 10:
                changed += 1
        return {
            "mean_abs_rgb_delta": round(float(mean_abs), 3),
            "changed_pixel_ratio": round(changed / total, 5),
        }


async def run_terrain_3d_qa(
    args: argparse.Namespace, out_dir: Path
) -> Terrain3dQaResult:
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
        await wait_for_terrain_ready(page, args.timeout_ms)
        ui_metrics = await page.evaluate(
            """
            () => {
              const canvas = document.querySelector('#terrain-3d-canvas')?.getBoundingClientRect();
              const debug = document.querySelector('.debug-panel');
              const controls = document.querySelector('.controls');
              const topbar = document.querySelector('.topbar');
              const debugRect = debug?.getBoundingClientRect();
              const controlsRect = controls?.getBoundingClientRect();
              const topbarRect = topbar?.getBoundingClientRect();
              return {
                canvas_width_ratio: canvas ? canvas.width / window.innerWidth : 0,
                canvas_height_ratio: canvas ? canvas.height / window.innerHeight : 0,
                debug_panel_visible: Boolean(debugRect && debugRect.width > 0 && debugRect.height > 0),
                controls_visible: Boolean(controlsRect && controlsRect.width > 0 && controlsRect.height > 0),
                topbar_visible: Boolean(topbarRect && topbarRect.width > 0 && topbarRect.height > 0),
                aside_count: document.querySelectorAll('aside').length,
                exposed_debug_text: document.body.innerText.includes('"visualModel"')
              };
            }
            """
        )
        center_before = await page.evaluate(
            "() => window.floodTerrain3d.stats.centerTile"
        )

        canvas = page.locator("#terrain-3d-canvas")
        first = screenshots_dir / "terrain-3d-first.png"
        second = screenshots_dir / "terrain-3d-animation.png"
        moved = screenshots_dir / "terrain-3d-moved.png"
        await canvas.screenshot(path=str(first))
        await page.wait_for_timeout(900)
        await canvas.screenshot(path=str(second))
        await page.locator('[data-pan-tile="east"]').click()
        await page.wait_for_function(
            """
            (centerBefore) => {
              const stats = window.floodTerrain3d?.stats;
              return Boolean(
                stats?.ready &&
                stats?.tilesLoaded >= 9 &&
                stats?.navigationCount >= 1 &&
                stats?.centerTile?.x !== centerBefore?.x
              );
            }
            """,
            arg=center_before,
            timeout=args.timeout_ms,
        )
        await canvas.screenshot(path=str(moved))
        center_after = await page.evaluate(
            "() => window.floodTerrain3d.stats.centerTile"
        )
        stats = await page.evaluate("() => window.floodTerrain3d.stats")
        await page.goto(
            add_query_param(url, "debug=1"),
            wait_until="domcontentloaded",
            timeout=args.timeout_ms,
        )
        debug_panel_visible_when_enabled = await page.evaluate(
            """
            () => {
              const debug = document.querySelector('.debug-panel');
              const rect = debug?.getBoundingClientRect();
              return Boolean(rect && rect.width > 0 && rect.height > 0);
            }
            """
        )
        await browser.close()

    visual_metrics = visual_richness_metrics(first)
    visual_metrics.update(ui_metrics)
    visual_metrics["debug_panel_visible_when_enabled"] = (
        debug_panel_visible_when_enabled
    )
    visual_metrics["center_tile_moved"] = center_before != center_after
    visual_metrics.update(
        {f"animation_{k}": v for k, v in image_change_metrics(first, second).items()}
    )
    visual_metrics.update(
        {f"navigation_{k}": v for k, v in image_change_metrics(first, moved).items()}
    )

    failures = []
    if stats.get("visualModel") != "map-draped-terrain-hand-water-world-v2":
        failures.append("Unexpected or missing 3D visual model marker")
    if not stats.get("terrainLoaded"):
        failures.append("Terrain/elevation tile did not load")
    if stats.get("elevationSource") != "terrain-v2-elevation":
        failures.append("3D terrain did not use ORNL terrain-v2 elevation")
    if stats.get("meshSize", 0) < 192:
        failures.append("3D terrain mesh resolution is below the world baseline")
    if stats.get("tileCount", 0) < 9 or stats.get("tilesLoaded", 0) < 9:
        failures.append("3D scene did not load the expected multi-tile world")
    if stats.get("tileCacheHits", 0) < 6:
        failures.append("3D navigation did not reuse overlapping cached world tiles")
    if stats.get("tileCacheSize", 0) < 12:
        failures.append(
            "3D tile cache did not retain loaded world tiles after navigation"
        )
    if not stats.get("handLoaded"):
        failures.append("HAND tile did not load")
    if not stats.get("basemapCaptured"):
        failures.append("Basemap texture was not captured")
    if not stats.get("waterVisible"):
        failures.append("Water mesh was not visible")
    if stats.get("flowParticleCount", 0) < 100:
        failures.append("Drainage-flow particles were not generated")
    if visual_metrics["unique_sample_colors"] < 300:
        failures.append("3D canvas lacks visual richness")
    if visual_metrics["blueish_pixel_ratio"] < 0.015:
        failures.append("3D canvas does not show enough visible water")
    if visual_metrics["very_dark_pixel_ratio"] > 0.65:
        failures.append("3D canvas appears mostly blank/dark")
    if visual_metrics["animation_changed_pixel_ratio"] < 0.0005:
        failures.append("3D water animation did not visibly change frames")
    if not visual_metrics["center_tile_moved"]:
        failures.append("3D navigation did not move the world center tile")
    if visual_metrics["navigation_changed_pixel_ratio"] < 0.01:
        failures.append("3D navigation did not visibly change the terrain scene")
    if visual_metrics["canvas_width_ratio"] < 0.92:
        failures.append("3D canvas is not the default full-stage presentation")
    if visual_metrics["canvas_height_ratio"] < 0.92:
        failures.append("3D canvas does not fill the viewport height")
    if visual_metrics["debug_panel_visible"] or visual_metrics["exposed_debug_text"]:
        failures.append("Default 3D page exposes debug UI")
    if not visual_metrics["debug_panel_visible_when_enabled"]:
        failures.append("Debug panel did not appear with debug=1")
    if visual_metrics["aside_count"] != 0:
        failures.append("Default 3D page still uses a lab-style sidebar")
    if not visual_metrics["controls_visible"] or not visual_metrics["topbar_visible"]:
        failures.append("Production controls/topbar are not visible")
    if stats.get("errors"):
        failures.append(f"3D app reported errors: {stats['errors']}")
    if console_errors:
        failures.append(f"Console errors: {console_errors[:5]}")
    if page_errors:
        failures.append(f"Page errors: {page_errors[:5]}")
    if failed_requests:
        failures.append(f"Failed requests: {failed_requests[:5]}")
    if bad_responses:
        failures.append(f"Bad responses: {bad_responses[:5]}")

    return Terrain3dQaResult(
        pass_=not failures,
        url=url,
        screenshots={
            "first": str(first),
            "animation": str(second),
            "moved": str(moved),
        },
        stats=stats,
        visual_metrics=visual_metrics,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        bad_responses=bad_responses,
        failures=failures,
    )


def write_summary(out_dir: Path, result: Terrain3dQaResult) -> None:
    (out_dir / "summary.json").write_text(
        json.dumps(result.to_json(), indent=2), encoding="utf-8"
    )
    status = "PASS" if result.pass_ else "FAIL"
    lines = [
        f"# Terrain 3D QA: {status}",
        "",
        f"- URL: `{result.url}`",
        f"- Visual model: `{result.stats.get('visualModel')}`",
        f"- Tile: `{result.stats.get('tile')}`",
        f"- Tiles loaded: `{result.stats.get('tilesLoaded')}/{result.stats.get('tileCount')}`",
        f"- Tile cache: `{result.stats.get('tileCacheSize')}` entries, `{result.stats.get('tileCacheHits')}` hits",
        f"- HAND dataset: `{result.stats.get('handDatasetVersion')}`",
        f"- Water vertex ratio: `{result.stats.get('waterVertexRatio')}`",
        f"- Flow particles: `{result.stats.get('flowParticleCount')}`",
        f"- Unique sample colors: `{result.visual_metrics.get('unique_sample_colors')}`",
        f"- Blueish pixel ratio: `{result.visual_metrics.get('blueish_pixel_ratio')}`",
        f"- Canvas width ratio: `{result.visual_metrics.get('canvas_width_ratio')}`",
        f"- Debug panel visible: `{result.visual_metrics.get('debug_panel_visible')}`",
        f"- Animation changed pixel ratio: `{result.visual_metrics.get('animation_changed_pixel_ratio')}`",
        f"- Navigation changed pixel ratio: `{result.visual_metrics.get('navigation_changed_pixel_ratio')}`",
        f"- First screenshot: `{result.screenshots['first']}`",
        f"- Animation screenshot: `{result.screenshots['animation']}`",
        f"- Moved screenshot: `{result.screenshots['moved']}`",
    ]
    if result.failures:
        lines.extend(
            ["", "## Failures", *[f"- {failure}" for failure in result.failures]]
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = await run_terrain_3d_qa(args, out_dir)
    write_summary(out_dir, result)
    print(json.dumps(result.to_json(), indent=2))
    return 0 if result.pass_ else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

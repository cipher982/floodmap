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

from playwright.async_api import async_playwright

DEFAULT_PATH = "/?lat=33.5186&lng=-86.8104&zoom=11.3&view=hand&water=10&handGpu=1"


@dataclass(frozen=True)
class ProductQaResult:
    pass_: bool
    url: str
    screenshots: dict[str, str]
    stats_before: dict
    stats_after: dict
    metadata: dict
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
        initial_path = screenshots_dir / "real-map-initial.png"
        await page.screenshot(path=str(initial_path), full_page=False)

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
        await page.screenshot(path=str(panned_path), full_page=False)
        await browser.close()

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
    if stats_after.get("visualModel") != "terrain-gradient-current-v1":
        failures.append("terrain-current visual model not active")
    if stats_after.get("tileTextureCount", 0) <= 0:
        failures.append("no real HAND tile textures loaded")
    if stats_after.get("textureUploads", 0) <= 0:
        failures.append("no HAND texture uploads")
    if stats_after.get("renderCount", 0) <= render_count_before:
        failures.append("animated layer did not repaint")

    return ProductQaResult(
        pass_=not failures,
        url=url,
        screenshots={
            "initial": str(initial_path),
            "panned": str(panned_path),
        },
        stats_before=stats_before,
        stats_after=stats_after,
        metadata=metadata,
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
        f"- Initial screenshot: `{Path(summary['screenshots']['initial']).name}`",
        f"- Panned screenshot: `{Path(summary['screenshots']['panned']).name}`",
        "",
    ]
    if summary["failures"]:
        lines.append("## Failures")
        lines.extend(f"- {failure}" for failure in summary["failures"])
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

#!/usr/bin/env python3
"""Run Flood Sandbox lab browser QA and write replayable artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

SCENARIOS = ("flat", "slope", "bowl", "ridge", "channel")


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    pass_: bool
    screenshot: str
    metrics: dict
    console_errors: list[str]
    page_errors: list[str]
    failed_requests: list[str]

    def to_json(self) -> dict:
        return {
            "scenario": self.scenario,
            "pass": self.pass_,
            "screenshot": self.screenshot,
            "metrics": self.metrics,
            "console_errors": self.console_errors,
            "page_errors": self.page_errors,
            "failed_requests": self.failed_requests,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--steps", type=int, default=360)
    parser.add_argument("--size", type=int, default=96)
    parser.add_argument("--backend", default="auto", choices=("auto", "webgpu", "cpu"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=45000)
    return parser.parse_args()


def default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("docs/qa/flood-sandbox/runs") / stamp


def scenario_url(
    base_url: str, scenario: str, steps: int, size: int, backend: str
) -> str:
    query = urlencode(
        {
            "autorun": "1",
            "scenario": scenario,
            "steps": str(steps),
            "size": str(size),
            "backend": backend,
        }
    )
    return f"{base_url.rstrip('/')}/sim-lab?{query}"


async def run_scenario(
    browser, args: argparse.Namespace, out_dir: Path, scenario: str
) -> ScenarioResult:
    page = await browser.new_page(
        viewport={"width": 1440, "height": 900}, device_scale_factor=1
    )
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

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

    url = scenario_url(args.base_url, scenario, args.steps, args.size, args.backend)
    await page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
    await page.wait_for_function(
        "() => window.floodSimLab && window.floodSimLab.summary && window.floodSimLab.summary.done",
        timeout=args.timeout_ms,
    )
    summary = await page.evaluate("() => window.floodSimLab.summary")
    status = await page.evaluate("() => window.floodSimLab.status")
    screenshot_path = out_dir / "screenshots" / f"{scenario}.png"
    await page.screenshot(path=str(screenshot_path), full_page=False)
    await page.close()

    metrics = {
        "url": url,
        "status": status,
        "summary": summary,
    }
    pass_ = (
        bool(summary.get("pass"))
        and not console_errors
        and not page_errors
        and not failed_requests
        and summary.get("finalMetrics", {}).get("nanCount") == 0
        and summary.get("finalMetrics", {}).get("negativeDepthCount") == 0
    )
    metrics_path = out_dir / "metrics" / f"{scenario}.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")
    return ScenarioResult(
        scenario=scenario,
        pass_=pass_,
        screenshot=str(screenshot_path),
        metrics=metrics,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
    )


async def main() -> int:
    args = parse_args()
    scenarios = tuple(s.strip() for s in args.scenarios.split(",") if s.strip())
    unknown = sorted(set(scenarios) - set(SCENARIOS))
    if unknown:
        raise SystemExit(f"Unknown scenarios: {', '.join(unknown)}")

    out_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics").mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=not args.headed,
            args=[
                "--disable-dev-shm-usage",
                "--enable-unsafe-webgpu",
                "--enable-webgpu",
                "--ignore-gpu-blocklist",
            ],
        )
        results = [
            await run_scenario(browser, args, out_dir, scenario)
            for scenario in scenarios
        ]
        await browser.close()

    any_webgpu = any(
        result.metrics["summary"].get("backend") == "webgpu" for result in results
    )
    all_pass = all(result.pass_ for result in results)
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "steps": args.steps,
        "size": args.size,
        "backend": args.backend,
        "any_webgpu": any_webgpu,
        "pass": all_pass and (args.backend != "webgpu" or any_webgpu),
        "results": [result.to_json() for result in results],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_markdown(out_dir / "summary.md", summary)
    print(json.dumps({"output_dir": str(out_dir), **summary}, indent=2))
    return 0 if summary["pass"] else 1


def write_markdown(path: Path, summary: dict) -> None:
    lines = [
        "# Flood Sandbox Lab QA",
        "",
        f"- Pass: `{summary['pass']}`",
        f"- Base URL: `{summary['base_url']}`",
        f"- Grid: `{summary['size']}x{summary['size']}`",
        f"- Steps: `{summary['steps']}`",
        f"- Any WebGPU backend: `{summary['any_webgpu']}`",
        "",
        "| Scenario | Pass | Backend | Water mass | Max depth | Screenshot |",
        "|---|---:|---|---:|---:|---|",
    ]
    for result in summary["results"]:
        scenario_summary = result["metrics"]["summary"]
        final = scenario_summary["finalMetrics"]
        screenshot = Path(result["screenshot"]).name
        lines.append(
            f"| {result['scenario']} | `{result['pass']}` | {scenario_summary['backend']} | "
            f"{final['waterMass']:.3f} | {final['maxDepth']:.3f} | `screenshots/{screenshot}` |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

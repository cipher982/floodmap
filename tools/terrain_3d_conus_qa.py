#!/usr/bin/env python3
"""Run the 3D terrain browser QA across representative CONUS locations."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from terrain_3d_qa import run_terrain_3d_qa, write_summary


@dataclass(frozen=True)
class Terrain3dQaCase:
    name: str
    lat: float
    lng: float
    zoom: int
    water: float
    exaggeration: float = 2.0

    def path(self) -> str:
        return (
            f"/terrain-3d?lat={self.lat}&lng={self.lng}&zoom={self.zoom}"
            f"&water={self.water}&exaggeration={self.exaggeration}"
        )


DEFAULT_CASES = (
    Terrain3dQaCase("birmingham", 33.5186, -86.8104, 12, 28),
    Terrain3dQaCase("saco", 43.25, -70.95, 12, 18),
    Terrain3dQaCase("atlanta", 33.7490, -84.3880, 12, 24),
    Terrain3dQaCase("phoenix", 33.4484, -112.0740, 12, 22),
    Terrain3dQaCase("denver", 39.7392, -104.9903, 12, 24),
    Terrain3dQaCase("sacramento", 38.5816, -121.4944, 12, 18),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://100.125.140.78:18000")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--timeout-ms", type=int, default=150000)
    parser.add_argument(
        "--case",
        action="append",
        choices=[case.name for case in DEFAULT_CASES],
        help="Run only the named case. Can be repeated.",
    )
    return parser.parse_args()


def default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("docs/qa/terrain-3d/conus-runs") / stamp


async def main() -> int:
    args = parse_args()
    output_root = Path(args.output_dir) if args.output_dir else default_output_dir()
    output_root.mkdir(parents=True, exist_ok=True)

    selected = set(args.case or [])
    cases = [case for case in DEFAULT_CASES if not selected or case.name in selected]
    results = []
    for case in cases:
        case_dir = output_root / case.name
        case_dir.mkdir(parents=True, exist_ok=True)
        qa_args = SimpleNamespace(
            base_url=args.base_url,
            path=case.path(),
            output_dir=str(case_dir),
            headed=False,
            timeout_ms=args.timeout_ms,
        )
        result = await run_terrain_3d_qa(qa_args, case_dir)
        write_summary(case_dir, result)
        results.append(
            {
                "name": case.name,
                "pass": result.pass_,
                "url": result.url,
                "stats": result.stats,
                "visual_metrics": result.visual_metrics,
                "failures": result.failures,
            }
        )

    passed = sum(1 for result in results if result["pass"])
    summary = {
        "pass": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    lines = [
        f"# Terrain 3D CONUS QA: {'PASS' if summary['pass'] else 'FAIL'}",
        "",
        f"- Passed: `{passed}/{len(results)}`",
        "",
    ]
    for result in results:
        status = "PASS" if result["pass"] else "FAIL"
        stats = result["stats"]
        lines.append(
            f"- {status} `{result['name']}`: `{stats.get('tilesLoaded')}/{stats.get('tileCount')}` tiles, "
            f"`{stats.get('flowRibbonCount')}` ribbons, `{stats.get('flowSimulationModel')}`"
        )
        if result["failures"]:
            lines.extend(f"  - {failure}" for failure in result["failures"])
    (output_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

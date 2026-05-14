from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

TILE_SIZE = 256
UINT16_BYTES = 2
U16_TILE_BYTES = TILE_SIZE * TILE_SIZE * UINT16_BYTES


@dataclass(frozen=True)
class BBox:
    name: str
    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True)
class ZoomEstimate:
    z: int
    tile_count: int
    raw_bytes: int


@dataclass(frozen=True)
class PyramidEstimate:
    bbox: BBox
    min_zoom: int
    max_zoom: int
    zooms: list[ZoomEstimate]

    @property
    def total_tiles(self) -> int:
        return sum(zoom.tile_count for zoom in self.zooms)

    @property
    def total_raw_bytes(self) -> int:
        return sum(zoom.raw_bytes for zoom in self.zooms)


@dataclass(frozen=True)
class SourceRasterEstimate:
    name: str
    area_km2: float
    cell_size_m: float
    bytes_per_cell: int = UINT16_BYTES
    overview_multiplier: float = 4.0 / 3.0

    @property
    def cell_count(self) -> int:
        return round(self.area_km2 * 1_000_000 / (self.cell_size_m**2))

    @property
    def raw_bytes(self) -> int:
        return self.cell_count * self.bytes_per_cell

    @property
    def raw_bytes_with_overviews(self) -> int:
        return round(self.raw_bytes * self.overview_multiplier)


DEFAULT_BBOXES = [
    BBox("CONUS bbox", -125.0, 24.0, -66.5, 49.5),
    BBox("Alaska bbox", -170.0, 51.0, -129.0, 72.0),
    BBox("Hawaii bbox", -161.0, 18.5, -154.0, 22.5),
    BBox("Puerto Rico/VI bbox", -68.2, 17.5, -64.5, 18.7),
]

# Rounded land/water target areas for order-of-magnitude source-raster storage.
# These are intentionally estimates; tile counts are exact for the configured bboxes.
DEFAULT_SOURCE_RASTERS = [
    SourceRasterEstimate("CONUS land-ish 10m HAND", area_km2=8_080_000, cell_size_m=10),
    SourceRasterEstimate(
        "All-US land-ish 10m HAND", area_km2=9_830_000, cell_size_m=10
    ),
    SourceRasterEstimate("CONUS land-ish 30m HAND", area_km2=8_080_000, cell_size_m=30),
    SourceRasterEstimate(
        "All-US land-ish 30m HAND", area_km2=9_830_000, cell_size_m=30
    ),
]


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    x = math.floor((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_count_for_bbox(bbox: BBox, z: int) -> int:
    x0, y_top = lonlat_to_tile(bbox.west, bbox.north, z)
    x1, y_bottom = lonlat_to_tile(bbox.east, bbox.south, z)
    return max(0, x1 - x0 + 1) * max(0, y_bottom - y_top + 1)


def estimate_pyramid(bbox: BBox, min_zoom: int, max_zoom: int) -> PyramidEstimate:
    zooms = [
        ZoomEstimate(z=z, tile_count=count, raw_bytes=count * U16_TILE_BYTES)
        for z in range(min_zoom, max_zoom + 1)
        for count in [tile_count_for_bbox(bbox, z)]
    ]
    return PyramidEstimate(bbox=bbox, min_zoom=min_zoom, max_zoom=max_zoom, zooms=zooms)


def summarize_regions(
    bboxes: Iterable[BBox] = DEFAULT_BBOXES, min_zoom: int = 9, max_zoom: int = 14
) -> list[PyramidEstimate]:
    return [estimate_pyramid(bbox, min_zoom, max_zoom) for bbox in bboxes]


def measure_u16_tile_dir(path: Path) -> dict[str, int]:
    files = sorted(path.rglob("*.u16"))
    return {
        "tile_count": len(files),
        "raw_bytes": sum(file.stat().st_size for file in files),
    }


def format_bytes(byte_count: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(byte_count)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{value:.1f} TB"


def estimates_to_dict(
    estimates: list[PyramidEstimate],
    sources: list[SourceRasterEstimate],
    artifact: dict[str, int] | None,
) -> dict:
    return {
        "tile_bytes": U16_TILE_BYTES,
        "pyramids": [
            {
                "bbox": asdict(estimate.bbox),
                "min_zoom": estimate.min_zoom,
                "max_zoom": estimate.max_zoom,
                "total_tiles": estimate.total_tiles,
                "total_raw_bytes": estimate.total_raw_bytes,
                "zooms": [asdict(zoom) for zoom in estimate.zooms],
            }
            for estimate in estimates
        ],
        "source_rasters": [
            {
                **asdict(source),
                "cell_count": source.cell_count,
                "raw_bytes": source.raw_bytes,
                "raw_bytes_with_overviews": source.raw_bytes_with_overviews,
            }
            for source in sources
        ],
        "artifact": artifact,
    }


def format_markdown(data: dict) -> str:
    lines = [
        "# HAND Storage Estimate",
        "",
        f"Raw `.u16` web tile size: `{data['tile_bytes']}` bytes.",
        "",
        "## Static Web Tile Pyramids",
        "",
        "| Region | Max zoom | Tiles | Raw bytes |",
        "|---|---:|---:|---:|",
    ]
    for pyramid in data["pyramids"]:
        lines.append(
            "| {name} | {max_zoom} | {tiles:,} | {bytes} |".format(
                name=pyramid["bbox"]["name"],
                max_zoom=pyramid["max_zoom"],
                tiles=pyramid["total_tiles"],
                bytes=format_bytes(pyramid["total_raw_bytes"]),
            )
        )

    lines.extend(
        [
            "",
            "## Source Raster Order Of Magnitude",
            "",
            "| Model | Cells | Raw | Raw + overviews |",
            "|---|---:|---:|---:|",
        ]
    )
    for source in data["source_rasters"]:
        lines.append(
            "| {name} | {cells:,} | {raw} | {overviews} |".format(
                name=source["name"],
                cells=source["cell_count"],
                raw=format_bytes(source["raw_bytes"]),
                overviews=format_bytes(source["raw_bytes_with_overviews"]),
            )
        )

    if data.get("artifact"):
        artifact = data["artifact"]
        lines.extend(
            [
                "",
                "## Measured Local Artifact",
                "",
                f"- Tiles: `{artifact['tile_count']:,}`",
                f"- Raw bytes: `{format_bytes(artifact['raw_bytes'])}`",
            ]
        )

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate HAND storage budgets.")
    parser.add_argument("--min-zoom", type=int, default=9)
    parser.add_argument("--max-zoom", type=int, default=14)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("src/web/prototypes/birmingham-drainage/tiles"),
        help="Optional local .u16 tile artifact directory to measure.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact = measure_u16_tile_dir(args.artifact) if args.artifact.exists() else None
    data = estimates_to_dict(
        summarize_regions(min_zoom=args.min_zoom, max_zoom=args.max_zoom),
        DEFAULT_SOURCE_RASTERS,
        artifact,
    )
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_markdown(data))


if __name__ == "__main__":
    main()

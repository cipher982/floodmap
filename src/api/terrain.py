"""Shared terrain-layer primitives for national raster value products.

This module defines the v2 terrain contract without wiring it into live routes
yet. It intentionally keeps HAND/elevation value encoding explicit so the new
drainage-relative layer cannot accidentally reuse absolute-elevation decoding.
"""

from __future__ import annotations

import math
import struct
from enum import StrEnum
from typing import Literal

import numpy as np
from config import IS_DEVELOPMENT, TILE_CACHE_CONTROL, TILE_SIZE
from pydantic import BaseModel, Field, field_validator, model_validator

U16_NODATA = np.uint16(65535)
U16_TILE_BYTES = TILE_SIZE * TILE_SIZE * np.dtype(np.uint16).itemsize
TERRAIN_BATCH_MAGIC = b"FMT2"
TERRAIN_BATCH_VERSION = 1
TERRAIN_BATCH_TILE_META_BYTES = 9  # uint8 z + uint32 x + uint32 y
MAX_TERRAIN_BATCH_TILES = 24


class TerrainEncoding(StrEnum):
    ELEVATION_METER_RANGE = "elevation-meter-range"
    HAND_DECIMETERS = "uint16-decimeters"


class TerrainRegion(BaseModel):
    id: str = Field(..., min_length=1)
    bbox: tuple[float, float, float, float]
    crs: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        west, south, east, north = value
        if not (-180 <= west < east <= 180):
            raise ValueError(
                "bbox longitude order must be west < east within [-180, 180]"
            )
        if not (-90 <= south < north <= 90):
            raise ValueError(
                "bbox latitude order must be south < north within [-90, 90]"
            )
        return value

    def contains(self, lon: float, lat: float) -> bool:
        west, south, east, north = self.bbox
        return west <= lon <= east and south <= lat <= north


class TerrainLayer(BaseModel):
    encoding: TerrainEncoding
    nodata: int = int(U16_NODATA)
    regions: list[TerrainRegion] = Field(default_factory=list)

    @field_validator("nodata")
    @classmethod
    def validate_nodata(cls, value: int) -> int:
        if value != int(U16_NODATA):
            raise ValueError("terrain v2 currently reserves 65535 as nodata")
        return value


class TerrainManifest(BaseModel):
    schema_version: int = 1
    dataset_version: str = Field(..., min_length=1)
    layers: dict[str, TerrainLayer]

    @model_validator(mode="after")
    def validate_layers(self) -> TerrainManifest:
        if not self.layers:
            raise ValueError("manifest must define at least one terrain layer")
        return self

    def find_region(self, layer: str, lon: float, lat: float) -> TerrainRegion | None:
        terrain_layer = self.layers.get(layer)
        if terrain_layer is None:
            return None
        return next(
            (region for region in terrain_layer.regions if region.contains(lon, lat)),
            None,
        )


class TerrainTileRequest(BaseModel):
    z: int = Field(..., ge=0, le=22)
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_xyz(self) -> TerrainTileRequest:
        max_coord = 2**self.z
        if self.x >= max_coord or self.y >= max_coord:
            raise ValueError("tile coordinate outside zoom range")
        return self


class TerrainBatchRequest(BaseModel):
    tiles: list[TerrainTileRequest] = Field(
        ..., min_length=1, max_length=MAX_TERRAIN_BATCH_TILES
    )

    def unique_tiles(self) -> list[TerrainTileRequest]:
        seen: set[tuple[int, int, int]] = set()
        unique: list[TerrainTileRequest] = []
        for tile in self.tiles:
            key = (tile.z, tile.x, tile.y)
            if key in seen:
                continue
            seen.add(key)
            unique.append(tile)
        return unique


def lonlat_to_tile_pixel(
    lon: float, lat: float, zoom: int
) -> tuple[int, int, int, int]:
    clipped_lat = max(-85.05112878, min(85.05112878, lat))
    scale = 2**zoom
    x_float = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(clipped_lat)
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
    tile_x = int(math.floor(x_float))
    tile_y = int(math.floor(y_float))
    pixel_x = min(TILE_SIZE - 1, max(0, int((x_float - tile_x) * TILE_SIZE)))
    pixel_y = min(TILE_SIZE - 1, max(0, int((y_float - tile_y) * TILE_SIZE)))
    return tile_x, tile_y, pixel_x, pixel_y


def empty_u16_tile() -> bytes:
    return np.full((TILE_SIZE, TILE_SIZE), U16_NODATA, dtype=np.uint16).tobytes()


def encode_hand_meters(values_m: np.ndarray) -> np.ndarray:
    """Encode HAND meters as uint16 decimeters with 65535 nodata."""
    values = np.asarray(values_m, dtype=np.float32)
    valid = np.isfinite(values) & (values >= 0)
    encoded = np.full(values.shape, U16_NODATA, dtype=np.uint16)
    scaled = np.clip(np.round(values[valid] * 10.0), 0, int(U16_NODATA) - 1)
    encoded[valid] = scaled.astype(np.uint16)
    return encoded


def decode_hand_meters(values_u16: np.ndarray) -> np.ndarray:
    values = np.asarray(values_u16, dtype=np.uint16)
    decoded = values.astype(np.float32) / 10.0
    decoded[values == U16_NODATA] = np.nan
    return decoded


def encode_elevation_meters(
    values_m: np.ndarray, nodata_value: int = -32768
) -> np.ndarray:
    """Encode absolute elevation using the existing v1 -500m..9000m mapping."""
    values = np.asarray(values_m, dtype=np.float32)
    invalid = (
        ~np.isfinite(values)
        | (values == nodata_value)
        | (values < -500)
        | (values > 9000)
    )
    encoded = np.full(values.shape, U16_NODATA, dtype=np.uint16)
    normalized = np.clip((values[~invalid] + 500) / 9500 * 65534, 0, 65534)
    encoded[~invalid] = normalized.astype(np.uint16)
    return encoded


def decode_elevation_meters(values_u16: np.ndarray) -> np.ndarray:
    values = np.asarray(values_u16, dtype=np.uint16)
    decoded = values.astype(np.float32) / 65534 * 9500 - 500
    decoded[values == U16_NODATA] = np.nan
    return decoded


def serialize_terrain_batch(
    tiles: list[TerrainTileRequest], tile_payloads: list[bytes]
) -> bytes:
    """Pack v2 terrain tiles; x/y are uint32-safe through z22."""
    if len(tiles) != len(tile_payloads):
        raise ValueError("tile metadata count must match payload count")
    if len(tiles) > MAX_TERRAIN_BATCH_TILES:
        raise ValueError(f"batch cannot exceed {MAX_TERRAIN_BATCH_TILES} tiles")

    tile_count = len(tiles)
    header_length = 7 + (tile_count * TERRAIN_BATCH_TILE_META_BYTES)
    payload = bytearray(header_length + (tile_count * U16_TILE_BYTES))
    payload[0:4] = TERRAIN_BATCH_MAGIC
    payload[4] = TERRAIN_BATCH_VERSION
    struct.pack_into("<H", payload, 5, tile_count)

    meta_offset = 7
    data_offset = header_length
    for tile, tile_bytes in zip(tiles, tile_payloads, strict=True):
        if len(tile_bytes) != U16_TILE_BYTES:
            raise ValueError(
                f"Unexpected tile byte length for {tile.z}/{tile.x}/{tile.y}: "
                f"{len(tile_bytes)}"
            )
        struct.pack_into("<BII", payload, meta_offset, tile.z, tile.x, tile.y)
        meta_offset += TERRAIN_BATCH_TILE_META_BYTES
        payload[data_offset : data_offset + U16_TILE_BYTES] = tile_bytes
        data_offset += U16_TILE_BYTES

    return bytes(payload)


def terrain_cache_control(kind: Literal["hit", "source_nodata", "build_miss"]) -> str:
    if kind in ("hit", "source_nodata"):
        return TILE_CACHE_CONTROL
    if IS_DEVELOPMENT:
        return "no-cache, no-store, must-revalidate"
    return "public, max-age=3600"


def terrain_tile_headers(
    *,
    dataset_version: str,
    layer: str,
    source: str,
    cache_status: Literal["HIT", "MISS"],
    data_status: Literal["ok", "source-nodata", "build-miss"] = "ok",
    content_encoding: str | None = None,
) -> dict[str, str]:
    cache_kind: Literal["hit", "source_nodata", "build_miss"]
    if data_status == "build-miss":
        cache_kind = "build_miss"
    elif data_status == "source-nodata":
        cache_kind = "source_nodata"
    else:
        cache_kind = "hit"

    headers = {
        "Cache-Control": terrain_cache_control(cache_kind),
        "Access-Control-Allow-Origin": "*",
        "Vary": "Accept-Encoding",
        "X-Terrain-Layer": layer,
        "X-Terrain-Dataset-Version": dataset_version,
        "X-Terrain-Source": source,
        "X-Terrain-Data-Status": data_status,
        "X-Cache": cache_status,
    }
    if content_encoding:
        headers["Content-Encoding"] = content_encoding
    return headers

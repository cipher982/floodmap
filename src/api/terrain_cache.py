"""Persistent terrain tile cache for rendered raw-value tiles."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from terrain import U16_TILE_BYTES, maybe_compress

try:
    import brotli  # type: ignore
except Exception:  # pragma: no cover - runtime dependency guard
    brotli = None

TerrainDataStatus = Literal["ok", "source-nodata"]


@dataclass(frozen=True)
class CachedTerrainTile:
    payload: bytes
    content_encoding: str | None
    data_status: TerrainDataStatus
    path: Path


@dataclass(frozen=True)
class TerrainCacheStats:
    tile_count: int
    compressed_bytes: int


class TerrainTileCache:
    """Store rendered v2 terrain tiles as `.u16.br` files.

    Layout:
      {root}/{layer}/{dataset_version}/{z}/{x}/{y}.u16.br
      {root}/{layer}/{dataset_version}/{z}/{x}/{y}.json
    """

    def __init__(self, root: Path):
        self.root = root

    def tile_dir(self, layer: str, dataset_version: str, z: int, x: int) -> Path:
        return self.root / layer / dataset_version / str(z) / str(x)

    def br_path(self, layer: str, dataset_version: str, z: int, x: int, y: int) -> Path:
        return self.tile_dir(layer, dataset_version, z, x) / f"{y}.u16.br"

    def meta_path(
        self, layer: str, dataset_version: str, z: int, x: int, y: int
    ) -> Path:
        return self.tile_dir(layer, dataset_version, z, x) / f"{y}.json"

    def read_tile(
        self,
        layer: str,
        dataset_version: str,
        z: int,
        x: int,
        y: int,
        accept_encoding: str,
    ) -> CachedTerrainTile | None:
        path = self.br_path(layer, dataset_version, z, x, y)
        if not path.exists():
            return None

        compressed = path.read_bytes()
        data_status = self._read_data_status(layer, dataset_version, z, x, y)
        if "br" in accept_encoding.lower() and brotli is not None:
            return CachedTerrainTile(
                payload=compressed,
                content_encoding="br",
                data_status=data_status,
                path=path,
            )

        if brotli is None:
            return None
        raw = brotli.decompress(compressed)  # type: ignore[union-attr]
        payload, content_encoding = maybe_compress(raw, accept_encoding)
        return CachedTerrainTile(
            payload=payload,
            content_encoding=content_encoding,
            data_status=data_status,
            path=path,
        )

    def read_raw_tile(
        self, layer: str, dataset_version: str, z: int, x: int, y: int
    ) -> CachedTerrainTile | None:
        return self.read_tile(layer, dataset_version, z, x, y, "identity")

    def write_tile(
        self,
        layer: str,
        dataset_version: str,
        z: int,
        x: int,
        y: int,
        raw_payload: bytes,
        data_status: TerrainDataStatus,
    ) -> Path:
        if len(raw_payload) != U16_TILE_BYTES:
            raise ValueError(f"terrain tile must be {U16_TILE_BYTES} bytes")
        if brotli is None:
            raise RuntimeError("brotli is required to write terrain tile cache")

        tile_dir = self.tile_dir(layer, dataset_version, z, x)
        tile_dir.mkdir(parents=True, exist_ok=True)
        path = self.br_path(layer, dataset_version, z, x, y)
        compressed = brotli.compress(raw_payload, quality=1)  # type: ignore[union-attr]
        self._atomic_write(path, compressed)
        self._atomic_write(
            self.meta_path(layer, dataset_version, z, x, y),
            (
                json.dumps(
                    {
                        "schema_version": 1,
                        "layer": layer,
                        "dataset_version": dataset_version,
                        "z": z,
                        "x": x,
                        "y": y,
                        "encoding": "br",
                        "data_status": data_status,
                        "raw_bytes": len(raw_payload),
                        "compressed_bytes": len(compressed),
                        "created_unix": time.time(),
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        return path

    def stats(
        self, layer: str | None = None, dataset_version: str | None = None
    ) -> TerrainCacheStats:
        root = self.root
        if layer is not None:
            root = root / layer
        if dataset_version is not None:
            root = root / dataset_version
        files = list(root.rglob("*.u16.br")) if root.exists() else []
        return TerrainCacheStats(
            tile_count=len(files),
            compressed_bytes=sum(path.stat().st_size for path in files),
        )

    def _read_data_status(
        self, layer: str, dataset_version: str, z: int, x: int, y: int
    ) -> TerrainDataStatus:
        path = self.meta_path(layer, dataset_version, z, x, y)
        if not path.exists():
            return "ok"
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get(
                "data_status", "ok"
            )
        except Exception:
            return "ok"
        return "source-nodata" if value == "source-nodata" else "ok"

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp_path.write_bytes(payload)
        os.replace(tmp_path, path)

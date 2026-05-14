"""Persistent terrain tile cache for rendered raw-value tiles."""

from __future__ import annotations

import json
import os
import time
from contextlib import suppress
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


@dataclass(frozen=True)
class TerrainCachePruneResult:
    before_tiles: int
    before_bytes: int
    after_tiles: int
    after_bytes: int
    removed_tiles: int
    removed_bytes: int


class TerrainTileCache:
    """Store rendered v2 terrain tiles as `.u16.br` files.

    Layout:
      {root}/{layer}/{dataset_version}/{z}/{x}/{y}.u16.br
      {root}/{layer}/{dataset_version}/{z}/{x}/{y}.json
    """

    def __init__(self, root: Path):
        self.root = root
        self._last_prune_unix_by_scope: dict[tuple[str | None, str | None], float] = {}

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
        self._atomic_write(path, compressed)
        return path

    def stats(
        self, layer: str | None = None, dataset_version: str | None = None
    ) -> TerrainCacheStats:
        # Maintenance-only scan. Do not call this from hot serving paths.
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

    def prune_to_size(
        self,
        max_bytes: int,
        layer: str | None = None,
        dataset_version: str | None = None,
        *,
        dry_run: bool = False,
    ) -> TerrainCachePruneResult:
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")

        # Maintenance scan: this is O(tile count), so keep it interval-gated or
        # run it out-of-band for national caches.
        root = self.root
        if layer is not None:
            root = root / layer
        if dataset_version is not None:
            root = root / dataset_version

        if root.exists() and not dry_run:
            for meta_path in root.rglob("*.json"):
                with suppress(FileNotFoundError):
                    if not meta_path.with_suffix(".u16.br").exists():
                        meta_path.unlink()

        files = sorted(
            root.rglob("*.u16.br") if root.exists() else [],
            key=lambda path: (path.stat().st_mtime, str(path)),
        )
        before_bytes = sum(path.stat().st_size for path in files)
        target_bytes = before_bytes
        removed_tiles = 0
        removed_bytes = 0

        for path in files:
            if target_bytes <= max_bytes:
                break
            size = path.stat().st_size
            target_bytes -= size
            removed_tiles += 1
            removed_bytes += size
            if dry_run:
                continue
            meta_path = path.with_suffix("").with_suffix(".json")
            with suppress(FileNotFoundError):
                path.unlink()
            with suppress(FileNotFoundError):
                meta_path.unlink()

        after_tiles = len(files) - removed_tiles
        after_bytes = before_bytes - removed_bytes
        if not dry_run:
            stats = self.stats(layer, dataset_version)
            after_tiles = stats.tile_count
            after_bytes = stats.compressed_bytes

        return TerrainCachePruneResult(
            before_tiles=len(files),
            before_bytes=before_bytes,
            after_tiles=after_tiles,
            after_bytes=after_bytes,
            removed_tiles=removed_tiles,
            removed_bytes=removed_bytes,
        )

    def maybe_prune_to_size(
        self,
        max_bytes: int,
        layer: str | None = None,
        dataset_version: str | None = None,
        *,
        min_interval_seconds: int = 60,
    ) -> TerrainCachePruneResult | None:
        if max_bytes <= 0:
            return None

        scope = (layer, dataset_version)
        now = time.time()
        last = self._last_prune_unix_by_scope.get(scope, 0.0)
        if now - last < min_interval_seconds:
            return None
        self._last_prune_unix_by_scope[scope] = now
        return self.prune_to_size(max_bytes, layer, dataset_version)

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

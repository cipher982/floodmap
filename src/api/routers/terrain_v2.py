from __future__ import annotations

from pathlib import Path

import numpy as np
from config import (
    BIRMINGHAM_HAND_COG_PATH,
    BIRMINGHAM_HAND_DATASET_VERSION,
    TERRAIN_CACHE_WRITE_THROUGH,
    TERRAIN_MANIFEST_PATH,
    TERRAIN_SAMPLE_CACHE_ZOOM,
    TERRAIN_TILE_CACHE_DIR,
)
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi import Path as PathParam
from pydantic import ValidationError
from terrain import (
    U16_NODATA,
    TerrainBatchRequest,
    TerrainManifest,
    TerrainTileRequest,
    lonlat_to_tile_pixel,
    maybe_compress,
    serialize_terrain_batch,
    terrain_tile_headers,
)
from terrain_cache import TerrainTileCache
from terrain_cog import render_cog_tile_with_cache, sample_cog_point, tile_bbox_lonlat
from terrain_manifest import (
    build_builtin_hand_manifest,
    load_terrain_manifest_from_path,
)

router = APIRouter(prefix="/api/v2/terrain", tags=["terrain-v2"])
terrain_tile_cache = TerrainTileCache(TERRAIN_TILE_CACHE_DIR)


def get_terrain_manifest() -> TerrainManifest:
    manifest = load_terrain_manifest_from_path(TERRAIN_MANIFEST_PATH)
    if manifest is not None:
        return manifest
    return build_builtin_hand_manifest(
        dataset_version=BIRMINGHAM_HAND_DATASET_VERSION,
        source_path=BIRMINGHAM_HAND_COG_PATH,
    )


def require_layer(
    manifest: TerrainManifest, layer: str, dataset_version: str
) -> TerrainLayer:
    if dataset_version != manifest.dataset_version:
        raise HTTPException(status_code=404, detail="Unknown terrain dataset version")
    terrain_layer = manifest.layers.get(layer)
    if terrain_layer is None:
        raise HTTPException(status_code=404, detail="Unknown terrain layer")
    return terrain_layer


def require_region_source_path(
    manifest: TerrainManifest, layer: str, region: TerrainRegion
) -> Path:
    source_url = region.url
    path = Path(source_url.removeprefix("file://"))
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Terrain source is not built for {region.id}: {path}",
            headers=terrain_tile_headers(
                dataset_version=manifest.dataset_version,
                layer=layer,
                source="manifest",
                cache_status="MISS",
                data_status="build-miss",
            ),
        )
    return path


def outside_coverage(layer: str, dataset_version: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="Tile outside terrain coverage",
        headers=terrain_tile_headers(
            dataset_version=dataset_version,
            layer=layer,
            source="manifest",
            cache_status="MISS",
            data_status="build-miss",
        ),
    )


def regions_for_tile(
    manifest: TerrainManifest, layer: str, z: int, x: int, y: int
) -> list[TerrainRegion]:
    bbox = tile_bbox_lonlat(z, x, y)
    regions = manifest.find_regions_for_bbox(layer, bbox)
    if not regions:
        raise outside_coverage(layer, manifest.dataset_version)
    return regions


def renderer_unavailable(
    layer: str, dataset_version: str, detail: str
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=detail,
        headers=terrain_tile_headers(
            dataset_version=dataset_version,
            layer=layer,
            source="dynamic-cog",
            cache_status="MISS",
            data_status="build-miss",
        ),
    )


def sample_cached_tile(
    layer: str, dataset_version: str, lat: float, lng: float
) -> tuple[bool, int | None]:
    tile_x, tile_y, pixel_x, pixel_y = lonlat_to_tile_pixel(
        lng, lat, TERRAIN_SAMPLE_CACHE_ZOOM
    )
    cached = terrain_tile_cache.read_raw_tile(
        layer, dataset_version, TERRAIN_SAMPLE_CACHE_ZOOM, tile_x, tile_y
    )
    if cached is None:
        return False, None
    values = np.frombuffer(cached.payload, dtype=np.uint16).reshape((256, 256))
    value = int(values[pixel_y, pixel_x])
    return True, None if value == int(U16_NODATA) else value


@router.get("/{layer}/{dataset_version}/{z}/{x}/{y}.u16")
def get_terrain_tile(
    layer: str,
    dataset_version: str,
    request: Request,
    z: int = PathParam(..., ge=0, le=22),
    x: int = PathParam(..., ge=0),
    y: int = PathParam(..., ge=0),
):
    try:
        TerrainTileRequest(z=z, x=x, y=y)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors(include_context=False)
        ) from exc
    manifest = get_terrain_manifest()
    require_layer(manifest, layer, dataset_version)
    tile_regions = regions_for_tile(manifest, layer, z, x, y)
    accept_encoding = request.headers.get("accept-encoding", "")

    cached = terrain_tile_cache.read_tile(
        layer, dataset_version, z, x, y, accept_encoding
    )
    if cached is not None:
        headers = terrain_tile_headers(
            dataset_version=dataset_version,
            layer=layer,
            source="persistent-cache",
            cache_status="HIT",
            data_status=cached.data_status,
            content_encoding=cached.content_encoding,
        )
        return Response(
            content=cached.payload,
            media_type="application/octet-stream",
            headers=headers,
        )

    source_path = require_region_source_path(manifest, layer, tile_regions[0])
    try:
        payload, cache_status, elapsed_ms = render_cog_tile_with_cache(
            source_path, z, x, y
        )
    except RuntimeError as exc:
        raise renderer_unavailable(layer, dataset_version, str(exc)) from exc
    values = np.frombuffer(payload, dtype=np.uint16)
    data_status = "source-nodata" if np.all(values == U16_NODATA) else "ok"
    if TERRAIN_CACHE_WRITE_THROUGH and data_status != "source-nodata":
        terrain_tile_cache.write_tile(
            layer, dataset_version, z, x, y, payload, data_status
        )
    response_payload, content_encoding = maybe_compress(payload, accept_encoding)
    headers = terrain_tile_headers(
        dataset_version=dataset_version,
        layer=layer,
        source="dynamic-cog",
        cache_status=cache_status,
        data_status=data_status,
        content_encoding=content_encoding,
    )
    headers["X-Terrain-Render-Ms"] = str(round(elapsed_ms, 2))
    return Response(
        content=response_payload,
        media_type="application/octet-stream",
        headers=headers,
    )


@router.post("/{layer}/{dataset_version}/batch.u16")
def get_terrain_tile_batch(
    layer: str,
    dataset_version: str,
    request: Request,
    batch_request: TerrainBatchRequest,
):
    manifest = get_terrain_manifest()
    require_layer(manifest, layer, dataset_version)

    unique_tiles = batch_request.unique_tiles()
    tile_payloads: list[bytes] = []
    cache_statuses: list[str] = []
    try:
        for tile in unique_tiles:
            tile_regions = regions_for_tile(manifest, layer, tile.z, tile.x, tile.y)
            cached = terrain_tile_cache.read_raw_tile(
                layer, dataset_version, tile.z, tile.x, tile.y
            )
            if cached is not None:
                tile_payloads.append(cached.payload)
                cache_statuses.append("HIT")
                continue

            source_path = require_region_source_path(manifest, layer, tile_regions[0])
            tile_payload, _, _ = render_cog_tile_with_cache(
                source_path, tile.z, tile.x, tile.y
            )
            values = np.frombuffer(tile_payload, dtype=np.uint16)
            data_status = "source-nodata" if np.all(values == U16_NODATA) else "ok"
            if TERRAIN_CACHE_WRITE_THROUGH and data_status != "source-nodata":
                terrain_tile_cache.write_tile(
                    layer,
                    dataset_version,
                    tile.z,
                    tile.x,
                    tile.y,
                    tile_payload,
                    data_status,
                )
            tile_payloads.append(tile_payload)
            cache_statuses.append("MISS")
    except RuntimeError as exc:
        raise renderer_unavailable(layer, dataset_version, str(exc)) from exc
    payload = serialize_terrain_batch(unique_tiles, tile_payloads)
    accept_encoding = request.headers.get("accept-encoding", "")
    response_payload, content_encoding = maybe_compress(payload, accept_encoding)
    all_cache_hit = cache_statuses and all(status == "HIT" for status in cache_statuses)
    headers = terrain_tile_headers(
        dataset_version=dataset_version,
        layer=layer,
        source="persistent-cache-batch" if all_cache_hit else "dynamic-cog-batch",
        cache_status="HIT" if all_cache_hit else "MISS",
        content_encoding=content_encoding,
    )
    headers["X-Tile-Count"] = str(len(unique_tiles))
    return Response(
        content=response_payload,
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get("/{layer}/metadata")
def get_terrain_metadata(layer: str):
    manifest = get_terrain_manifest()
    terrain_layer = manifest.layers.get(layer)
    if terrain_layer is None:
        raise HTTPException(status_code=404, detail="Unknown terrain layer")
    return {
        "schema_version": manifest.schema_version,
        "dataset_version": manifest.dataset_version,
        "layer": layer,
        "encoding": terrain_layer.encoding,
        "nodata": terrain_layer.nodata,
        "regions": [region.model_dump() for region in terrain_layer.regions],
        "tile_template": f"/api/v2/terrain/{layer}/{manifest.dataset_version}/{{z}}/{{x}}/{{y}}.u16",
        "batch_template": f"/api/v2/terrain/{layer}/{manifest.dataset_version}/batch.u16",
    }


@router.get("/{layer}/sample")
def sample_terrain(layer: str, lat: float, lng: float):
    manifest = get_terrain_manifest()
    terrain_layer = manifest.layers.get(layer)
    if terrain_layer is None:
        raise HTTPException(status_code=404, detail="Unknown terrain layer")
    region = manifest.find_region(layer, lng, lat)
    if region is None:
        raise HTTPException(status_code=404, detail="Point outside terrain coverage")
    sample_source = "source-cog"
    try:
        source_path = require_region_source_path(manifest, layer, region)
        value = sample_cog_point(source_path, lon=lng, lat=lat)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        has_cached_tile, value = sample_cached_tile(
            layer, manifest.dataset_version, lat, lng
        )
        sample_source = f"persistent-cache-z{TERRAIN_SAMPLE_CACHE_ZOOM}"
        if not has_cached_tile:
            raise
    except RuntimeError as exc:
        has_cached_tile, value = sample_cached_tile(
            layer, manifest.dataset_version, lat, lng
        )
        sample_source = f"persistent-cache-z{TERRAIN_SAMPLE_CACHE_ZOOM}"
        if not has_cached_tile:
            raise renderer_unavailable(
                layer, manifest.dataset_version, str(exc)
            ) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Point has no terrain data")
    height_m = value / 10.0
    return {
        "latitude": lat,
        "longitude": lng,
        "height_m": round(height_m, 2),
        "height_ft": round(height_m * 3.28084, 1),
        "encoding": terrain_layer.encoding,
        "dataset_version": manifest.dataset_version,
        "region": region.id,
        "sample_source": sample_source,
    }

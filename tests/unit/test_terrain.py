from __future__ import annotations

import math
import struct

import numpy as np
import pytest
from config import IS_DEVELOPMENT
from pydantic import ValidationError
from terrain import (
    TERRAIN_BATCH_MAGIC,
    TERRAIN_BATCH_TILE_META_BYTES,
    TERRAIN_BATCH_VERSION,
    U16_NODATA,
    U16_TILE_BYTES,
    TerrainBatchRequest,
    TerrainManifest,
    TerrainTileRequest,
    decode_elevation_meters,
    decode_hand_meters,
    empty_u16_tile,
    encode_elevation_meters,
    encode_hand_meters,
    lonlat_to_tile_pixel,
    serialize_terrain_batch,
    terrain_tile_headers,
)


def test_manifest_validates_regions_and_finds_matching_region():
    manifest = TerrainManifest.model_validate(
        {
            "schema_version": 1,
            "dataset_version": "hand-20260513a",
            "layers": {
                "hand": {
                    "encoding": "uint16-decimeters",
                    "nodata": 65535,
                    "regions": [
                        {
                            "id": "birmingham",
                            "bbox": [-87.02, 33.3, -86.52, 33.75],
                            "crs": "EPSG:5070",
                            "url": "file://data/terrain/hand/birmingham.tif",
                        }
                    ],
                }
            },
        }
    )

    region = manifest.find_region("hand", lon=-86.8025, lat=33.5207)
    assert region is not None
    assert region.id == "birmingham"
    assert manifest.find_region("hand", lon=-86.52, lat=33.5207) is None
    assert manifest.find_region("hand", lon=-80.0, lat=25.0) is None


def test_manifest_rejects_bad_bbox_and_wrong_nodata():
    with pytest.raises(ValidationError):
        TerrainManifest.model_validate(
            {
                "dataset_version": "bad",
                "layers": {
                    "hand": {
                        "encoding": "uint16-decimeters",
                        "nodata": 0,
                        "regions": [
                            {
                                "id": "bad",
                                "bbox": [-86.0, 33.0, -87.0, 34.0],
                                "crs": "EPSG:5070",
                                "url": "file://bad.tif",
                            }
                        ],
                    }
                },
            }
        )


def test_lonlat_to_tile_pixel_matches_known_birmingham_sample_tile():
    tile_x, tile_y, pixel_x, pixel_y = lonlat_to_tile_pixel(
        lon=-86.8025, lat=33.5207, zoom=12
    )

    assert (tile_x, tile_y) == (1060, 1642)
    assert 0 <= pixel_x < 256
    assert 0 <= pixel_y < 256


def test_hand_encoding_uses_decimeters_and_nodata():
    values = np.array([[0.0, 1.24], [math.nan, -1.0]], dtype=np.float32)

    encoded = encode_hand_meters(values)

    assert encoded.tolist() == [[0, 12], [int(U16_NODATA), int(U16_NODATA)]]
    decoded = decode_hand_meters(encoded)
    assert decoded[0, 0] == 0
    assert decoded[0, 1] == pytest.approx(1.2)
    assert math.isnan(decoded[1, 0])


def test_decoders_accept_read_only_arrays_from_tile_bytes():
    values = np.array([0, 10, int(U16_NODATA)], dtype=np.uint16)
    read_only = np.frombuffer(values.tobytes(), dtype=np.uint16)

    hand = decode_hand_meters(read_only)
    elevation = decode_elevation_meters(read_only)

    assert hand.tolist()[:2] == [0.0, 1.0]
    assert math.isnan(hand[2])
    assert elevation[0] == pytest.approx(-500.0)
    assert math.isnan(elevation[2])


def test_elevation_encoding_keeps_existing_v1_mapping():
    values = np.array(
        [[-500.0, 0.0, 9000.0], [math.nan, -32768, 9001]], dtype=np.float32
    )

    encoded = encode_elevation_meters(values)

    assert encoded[0, 0] == 0
    assert encoded[0, 1] > 0
    assert encoded[0, 2] == 65534
    assert encoded[1].tolist() == [int(U16_NODATA)] * 3
    assert decode_elevation_meters(encoded)[0, 1] == pytest.approx(0.0, abs=0.2)


def test_terrain_batch_uses_uint32_tile_coordinates():
    tile = TerrainTileRequest(z=18, x=262143, y=131071)
    tile_bytes = b"A" * U16_TILE_BYTES

    payload = serialize_terrain_batch([tile], [tile_bytes])

    assert payload[:4] == TERRAIN_BATCH_MAGIC
    assert payload[4] == TERRAIN_BATCH_VERSION
    assert struct.unpack_from("<H", payload, 5)[0] == 1
    assert struct.unpack_from("<BII", payload, 7) == (18, 262143, 131071)
    header_length = 7 + TERRAIN_BATCH_TILE_META_BYTES
    assert payload[header_length:] == tile_bytes


def test_batch_request_deduplicates_tiles():
    request = TerrainBatchRequest.model_validate(
        {"tiles": [{"z": 7, "x": 21, "y": 45}, {"z": 7, "x": 21, "y": 45}]}
    )

    assert request.unique_tiles() == [TerrainTileRequest(z=7, x=21, y=45)]


def test_batch_rejects_bad_payload_size():
    with pytest.raises(ValueError, match="Unexpected tile byte length"):
        serialize_terrain_batch([TerrainTileRequest(z=1, x=0, y=0)], [b"short"])


def test_empty_tile_is_fixed_size_nodata():
    values = np.frombuffer(empty_u16_tile(), dtype=np.uint16)

    assert values.size == 256 * 256
    assert np.all(values == U16_NODATA)


def test_terrain_headers_distinguish_source_nodata_from_build_miss():
    source_nodata = terrain_tile_headers(
        dataset_version="hand-20260513a",
        layer="hand",
        source="dynamic-cog",
        cache_status="MISS",
        data_status="source-nodata",
        content_encoding="br",
    )
    assert source_nodata["Content-Encoding"] == "br"
    assert source_nodata["X-Terrain-Data-Status"] == "source-nodata"
    if IS_DEVELOPMENT:
        assert "no-store" in source_nodata["Cache-Control"].lower()
    else:
        assert "immutable" in source_nodata["Cache-Control"].lower()

    build_miss = terrain_tile_headers(
        dataset_version="hand-20260513a",
        layer="hand",
        source="manifest",
        cache_status="MISS",
        data_status="build-miss",
    )
    assert build_miss["X-Terrain-Data-Status"] == "build-miss"
    assert "immutable" not in build_miss["Cache-Control"].lower()

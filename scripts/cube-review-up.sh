#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

BIND_IP="${BIND_IP:-100.125.140.78}"
API_PORT="${API_PORT:-18000}"
TILESERVER_PORT="${TILESERVER_PORT:-18080}"
FLOODMAP_DATA_ROOT="${FLOODMAP_DATA_ROOT:-/mnt/storage/floodmap/data}"
TERRAIN_MANIFEST_PATH="${TERRAIN_MANIFEST_PATH:-${FLOODMAP_DATA_ROOT}/terrain/manifest.json}"
TERRAIN_CACHE_MAX_BYTES="${TERRAIN_CACHE_MAX_BYTES:-21474836480}"
ENVIRONMENT="${ENVIRONMENT:-development}"
ALLOW_MISSING_DATA="${ALLOW_MISSING_DATA:-true}"
TILESERVER_URL="${TILESERVER_URL:-http://${BIND_IP}:${TILESERVER_PORT}}"
API_URL="http://${BIND_IP}:${API_PORT}"
TILESERVER_CONTAINER="${TILESERVER_CONTAINER:-floodmap-cube-tileserver}"
UV_BIN="${UV_BIN:-/home/drose/.local/bin/uv}"
LOG_FILE="${LOG_FILE:-/mnt/storage/floodmap/api-18000.log}"
PID_FILE="${PID_FILE:-/mnt/storage/floodmap/api-18000.pid}"
SMOKE_LAT="${SMOKE_LAT:-33.5186}"
SMOKE_LNG="${SMOKE_LNG:--86.8104}"
SMOKE_ZOOM="${SMOKE_ZOOM:-11}"
SMOKE_WATER="${SMOKE_WATER:-2.0}"
SMOKE_TILE_Z="${SMOKE_TILE_Z:-11}"
SMOKE_TILE_X="${SMOKE_TILE_X:-530}"
SMOKE_TILE_Y="${SMOKE_TILE_Y:-821}"

fail() {
    echo "error: $*" >&2
    exit 1
}

resolve_path() {
    readlink -f "$1"
}

assert_not_gemini() {
    local path="$1"
    local resolved
    resolved="$(resolve_path "$path")"
    case "$resolved" in
        /mnt/gemini|/mnt/gemini/*)
            fail "refusing to use quarantined Gemini path: ${resolved}"
            ;;
    esac
}

require_file() {
    local path="$1"
    [[ -f "$path" ]] || fail "missing required file: ${path}"
    assert_not_gemini "$path"
}

require_dir() {
    local path="$1"
    [[ -d "$path" ]] || fail "missing required directory: ${path}"
    assert_not_gemini "$path"
}

wait_for_url() {
    local url="$1"
    local label="$2"
    local attempts="${3:-30}"

    for _ in $(seq 1 "$attempts"); do
        if curl -fsS -o /dev/null "$url" 2>/dev/null; then
            echo "ok: ${label}"
            return 0
        fi
        sleep 1
    done

    fail "timed out waiting for ${label}: ${url}"
}

http_status() {
    local url="$1"
    local status
    status="$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)"
    printf "%s" "${status:-000}"
}

wait_for_status() {
    local url="$1"
    local expected="$2"
    local label="$3"
    local attempts="${4:-30}"
    local status="000"

    for _ in $(seq 1 "$attempts"); do
        status="$(http_status "$url")"
        if [[ "$status" == "$expected" ]]; then
            echo "ok: ${label} ${status}"
            return 0
        fi
        sleep 1
    done

    fail "${label} returned ${status}, expected ${expected}: ${url}"
}

stop_existing_api() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" || true
        fi
        rm -f "$PID_FILE"
    fi

    pkill -f "uvicorn main:app --host ${BIND_IP} --port ${API_PORT}" 2>/dev/null || true
}

write_tileserver_config() {
    local base_maps_dir="$1"
    cat > "${base_maps_dir}/config.json.tmp" <<'JSON'
{"options":{"paths":{"root":"/data","mbtiles":"/data"}},"data":{"usa-complete":{"mbtiles":"usa-complete.mbtiles"}}}
JSON
    mv "${base_maps_dir}/config.json.tmp" "${base_maps_dir}/config.json"
}

extract_dataset_version() {
    python3 - "$TERRAIN_MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
print(manifest["dataset_version"])
PY
}

echo "Floodmap Cube review startup"
echo "repo: ${REPO_ROOT}"
echo "data: ${FLOODMAP_DATA_ROOT}"
echo "api: ${API_URL}"
echo "tileserver: ${TILESERVER_URL}"

command -v docker >/dev/null || fail "docker is required"
command -v curl >/dev/null || fail "curl is required"
command -v python3 >/dev/null || fail "python3 is required"
[[ -x "$UV_BIN" ]] || UV_BIN="$(command -v uv || true)"
[[ -n "$UV_BIN" ]] || fail "uv is required"

require_dir "$REPO_ROOT/src/api"
require_dir "$FLOODMAP_DATA_ROOT"
require_file "${FLOODMAP_DATA_ROOT}/base-maps/usa-complete.mbtiles"
require_file "$TERRAIN_MANIFEST_PATH"
mkdir -p "${FLOODMAP_DATA_ROOT}/terrain/tile-cache"
assert_not_gemini "${FLOODMAP_DATA_ROOT}/terrain/tile-cache"

write_tileserver_config "${FLOODMAP_DATA_ROOT}/base-maps"

echo "starting tileserver-gl..."
docker rm -f "$TILESERVER_CONTAINER" >/dev/null 2>&1 || true
docker run -d \
    --name "$TILESERVER_CONTAINER" \
    --restart unless-stopped \
    -p "${BIND_IP}:${TILESERVER_PORT}:8080" \
    -v "${FLOODMAP_DATA_ROOT}/base-maps:/data:ro" \
    maptiler/tileserver-gl >/dev/null
wait_for_url "${TILESERVER_URL}/health" "tileserver health"

echo "starting FastAPI..."
stop_existing_api
(
    cd "$REPO_ROOT/src/api"
    nohup env \
        FLOODMAP_DATA_ROOT="$FLOODMAP_DATA_ROOT" \
        TERRAIN_MANIFEST_PATH="$TERRAIN_MANIFEST_PATH" \
        TERRAIN_V2_ENABLED=true \
        TERRAIN_CACHE_MAX_BYTES="$TERRAIN_CACHE_MAX_BYTES" \
        ENVIRONMENT="$ENVIRONMENT" \
        ALLOW_MISSING_DATA="$ALLOW_MISSING_DATA" \
        TILESERVER_URL="$TILESERVER_URL" \
        "$UV_BIN" run --with rasterio --with affine \
            uvicorn main:app --host "$BIND_IP" --port "$API_PORT" --log-level info \
            > "$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
)

wait_for_url "${API_URL}/api/health" "api health"

DATASET_VERSION="$(extract_dataset_version)"
wait_for_status "${API_URL}/api/v1/tiles/vector/usa/10/267/410.pbf" "200" "vector smoke"
wait_for_status "${API_URL}/api/v2/terrain/hand/metadata" "200" "HAND metadata"
wait_for_status "${API_URL}/api/v2/terrain/hand/sample?lat=${SMOKE_LAT}&lng=${SMOKE_LNG}" "200" "HAND sample"
wait_for_status "${API_URL}/api/v2/terrain/hand/${DATASET_VERSION}/${SMOKE_TILE_Z}/${SMOKE_TILE_X}/${SMOKE_TILE_Y}.u16" "200" "HAND tile"
echo "review URL: ${API_URL}/?lat=${SMOKE_LAT}&lng=${SMOKE_LNG}&zoom=${SMOKE_ZOOM}&view=hand&water=${SMOKE_WATER}"
echo "log: ${LOG_FILE}"

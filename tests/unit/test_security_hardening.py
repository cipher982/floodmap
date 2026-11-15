from __future__ import annotations

import importlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from middleware.rate_limiter import RateLimiter, RateLimitError, RateLimitMiddleware
from starlette.requests import Request


def _make_request(
    path: str = "/api/risk/location",
    client_host: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": raw_headers,
        "client": (client_host, 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


def _load_main_app(monkeypatch, *, environment: str, enable_diagnostics: str = "false"):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("ENABLE_DIAGNOSTICS", enable_diagnostics)
    monkeypatch.setenv("TERRAIN_V2_ENABLED", "true")

    for mod in list(sys.modules):
        if (
            mod in {"main", "config"}
            or mod == "routers"
            or mod.startswith("routers.")
            or mod == "middleware"
            or mod.startswith("middleware.")
        ):
            sys.modules.pop(mod, None)
    return importlib.import_module("main")


@pytest.mark.asyncio
async def test_rate_limiter_falls_back_to_local_when_redis_unavailable():
    limiter = RateLimiter()
    limiter.redis_client = None
    req = _make_request(client_host="198.51.100.10")

    await limiter.check_rate_limit(req, endpoint="places", limit=2)
    await limiter.check_rate_limit(req, endpoint="places", limit=2)

    with pytest.raises(RateLimitError):
        await limiter.check_rate_limit(req, endpoint="places", limit=2)


@pytest.mark.asyncio
async def test_rate_limiter_reraises_rate_limit_error_from_redis(monkeypatch):
    limiter = RateLimiter()
    limiter.redis_client = object()

    async def always_deny(key: str, limit: int, window: int = 1) -> bool:
        return False

    monkeypatch.setattr(limiter, "_is_redis_available", lambda: True)
    monkeypatch.setattr(limiter, "_redis_rate_limit", always_deny)

    req = _make_request(client_host="198.51.100.11")
    with pytest.raises(RateLimitError) as exc_info:
        await limiter.check_rate_limit(req, endpoint="places", limit=5)

    assert "local fallback" not in exc_info.value.detail["message"]


@pytest.mark.asyncio
async def test_rate_limiter_bounds_local_windows():
    limiter = RateLimiter(max_local_windows=100)
    limiter.redis_client = None

    for idx in range(250):
        req = _make_request(client_host=f"203.0.113.{idx % 250}")
        req.scope["client"] = (f"198.51.{idx // 250}.{idx % 250}", 1234)
        await limiter.check_rate_limit(req, endpoint="api", limit=30)

    assert len(limiter.local_windows) <= 100


def test_rate_limiter_trusts_cf_connecting_ip_only_from_private_or_loopback_peer():
    limiter = RateLimiter()

    public_peer_req = _make_request(
        client_host="198.51.100.20",
        headers={"CF-Connecting-IP": "203.0.113.99", "X-Forwarded-For": "203.0.113.88"},
    )
    assert limiter._get_client_ip(public_peer_req) == "198.51.100.20"

    loopback_peer_req = _make_request(
        client_host="127.0.0.1",
        headers={"CF-Connecting-IP": "203.0.113.99"},
    )
    assert limiter._get_client_ip(loopback_peer_req) == "203.0.113.99"

    private_peer_req = _make_request(
        client_host="172.18.0.5",
        headers={"CF-Connecting-IP": "203.0.113.77"},
    )
    assert limiter._get_client_ip(private_peer_req) == "203.0.113.77"


def test_rate_limit_middleware_route_categories_and_429_response(monkeypatch):
    from middleware import rate_limiter as rl_module

    test_limiter = RateLimiter()
    test_limiter.redis_client = None
    monkeypatch.setattr(rl_module, "rate_limiter", test_limiter)

    app = FastAPI()
    middleware = RateLimitMiddleware(app)
    assert (
        middleware._classify_request("/api/v1/tiles/vector/usa/0/0/0.pbf")[0] == "tiles"
    )
    assert middleware._classify_request("/api/v1/tiles/vector/usa/0/0/0.pbf")[1] >= 150
    assert middleware._classify_request(
        "/floodmap/api/v2/terrain/hand/v1/0/0/0.u16"
    ) == (
        "tiles",
        middleware.tiles_limit,
    )
    assert middleware._classify_request("/api/places/search") == ("places", 5)
    assert middleware._classify_request("/api/risk/location") == ("api", 30)
    assert middleware._classify_request("/api/v2/terrain/hand/sample") == ("api", 30)

    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/places/search")
    def places_route():
        return {"ok": True}

    @app.get("/api/risk/location")
    def api_route():
        return {"ok": True}

    @app.get("/api/v1/tiles/vector/usa/0/0/0.pbf")
    def tiles_route():
        return {"ok": True}

    client = TestClient(app)

    for _ in range(5):
        assert client.get("/api/places/search").status_code == 200
    limited = client.get("/api/places/search")
    assert limited.status_code == 429

    # Separate buckets: hitting places limit must not exhaust api or tiles buckets.
    assert client.get("/api/risk/location").status_code == 200
    for _ in range(150):
        assert client.get("/api/v1/tiles/vector/usa/0/0/0.pbf").status_code == 200


def test_prod_disables_docs_metrics_and_cache_endpoints(monkeypatch):
    main = _load_main_app(monkeypatch, environment="production")
    client = TestClient(main.app, base_url="https://testserver")

    for path in (
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
        "/api/metrics",
        "/api/cache",
    ):
        resp = client.get(path)
        assert resp.status_code == 404, (
            f"Expected 404 for {path} in prod, got {resp.status_code}"
        )


def test_health_and_terrain_v2_do_not_expose_internal_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("TERRAIN_REMOTE_BASE_URL", "")
    main = _load_main_app(monkeypatch, environment="production")
    from routers import terrain_v2

    missing_cog = tmp_path / "secret-dir" / "missing.tif"
    monkeypatch.setattr(terrain_v2, "BIRMINGHAM_HAND_COG_PATH", missing_cog)
    monkeypatch.setattr(
        terrain_v2, "TERRAIN_MANIFEST_PATH", tmp_path / "missing-manifest.json"
    )

    client = TestClient(main.app, base_url="https://testserver")

    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health_text = health_resp.text
    assert "deployment_context" not in health_resp.json()
    assert str(tmp_path) not in health_text
    assert "/app/data" not in health_text
    assert "terrain_remote_base_url" not in health_text

    meta_resp = client.get("/api/v2/terrain/hand/metadata")
    assert meta_resp.status_code == 200
    for region in meta_resp.json()["regions"]:
        assert "url" not in region

    tile_resp = client.get(
        f"/api/v2/terrain/hand/{terrain_v2.BIRMINGHAM_HAND_DATASET_VERSION}/0/0/0.u16"
    )
    assert tile_resp.status_code == 503
    assert str(missing_cog) not in tile_resp.text
    assert "secret-dir" not in tile_resp.text

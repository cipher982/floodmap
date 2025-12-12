from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_precompressed_miss_not_immutable(tmp_path: Path, monkeypatch):
    """A precompressed miss must not be cached as immutable for a year.

    Otherwise a transient data gap can be pinned in Cloudflare cache and users
    will see land rendered as NODATA until manual purges.
    """
    from routers import tiles_v1

    # Force "no tile exists" path.
    monkeypatch.setattr(tiles_v1, "PRECOMPRESSED_TILES_DIR", tmp_path, raising=True)

    app = FastAPI()
    app.include_router(tiles_v1.router)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/tiles/elevation-data/11/491/764.u16?method=precompressed",
        headers={"Accept-Encoding": "br"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Precompressed-Miss") == "1"

    cc = resp.headers.get("Cache-Control", "")
    assert "immutable" not in cc.lower()
    from config import IS_DEVELOPMENT

    if IS_DEVELOPMENT:
        assert "no-store" in cc.lower()
    else:
        assert "max-age=3600" in cc.replace(" ", "")

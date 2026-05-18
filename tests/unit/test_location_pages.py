from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def load_main_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_city_page_renders_unique_metadata_and_route_context(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_resp = client.get("/fl/tampa")
    subpath_resp = client.get("/floodmap/fl/tampa")

    assert root_resp.status_code == 200
    assert subpath_resp.status_code == 200
    assert root_resp.text == subpath_resp.text

    html = root_resp.text
    assert "<title>Tampa Flood Toy | Florida Water Map | FloodMap USA</title>" in html
    assert '<link rel="canonical" href="https://drose.io/floodmap/fl/tampa">' in html
    assert (
        '<meta property="og:url" content="https://drose.io/floodmap/fl/tampa">' in html
    )
    assert "Flood toy for Tampa, Florida" in html
    assert "Use this Tampa, Florida flood toy to inspect" in html
    assert '"pageType":"city"' in html
    assert '"stateSlug":"fl"' in html
    assert '"citySlug":"tampa"' in html
    assert '"view":"hand"' in html
    assert '"water":3.0' in html
    assert "__FLOODMAP_" not in html


def test_unknown_city_page_returns_404(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    resp = client.get("/zz/not-a-real-city")

    assert resp.status_code == 404

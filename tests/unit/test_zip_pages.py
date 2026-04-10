from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def load_main_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_zip_page_renders_noindex_metadata_headers_and_route_context(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_resp = client.get("/zip/33602")
    subpath_resp = client.get("/floodmap/zip/33602")

    assert root_resp.status_code == 200
    assert subpath_resp.status_code == 200
    assert root_resp.text == subpath_resp.text
    assert root_resp.headers["x-robots-tag"] == "noindex, follow"
    assert subpath_resp.headers["x-robots-tag"] == "noindex, follow"

    html = root_resp.text
    assert (
        "<title>ZIP 33602 Flood Map | Downtown Tampa, Tampa, Florida | FloodMap USA</title>"
        in html
    )
    assert '<link rel="canonical" href="https://drose.io/floodmap/zip/33602">' in html
    assert '<meta name="robots" content="noindex,follow">' in html
    assert "Flood map for ZIP 33602 in Tampa, Florida" in html
    assert "Use this ZIP 33602 flood map to inspect" in html
    assert 'href="../fl/tampa"' in html
    assert "Broader city flood map" in html
    assert '"pageType":"zip"' in html
    assert '"zipCode":"33602"' in html
    assert '"stateSlug":"fl"' in html
    assert '"citySlug":"tampa"' in html
    assert '"view":"flood"' in html
    assert '"water":3.0' in html
    assert "__FLOODMAP_" not in html


def test_unknown_zip_page_returns_404(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    resp = client.get("/zip/99999")

    assert resp.status_code == 404

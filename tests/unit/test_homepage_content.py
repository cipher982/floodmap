from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def load_main_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_homepage_contains_social_metadata_and_explanatory_copy(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    resp = client.get("/")

    assert resp.status_code == 200
    html = resp.text
    assert (
        "<title>FloodMap USA | Search ZIP Codes, Cities, Elevation &amp; Flood Risk</title>"
        in html
    )
    assert "Interactive U.S. flood map for any city or ZIP code." in html
    assert (
        'og:image" content="https://drose.io/floodmap/static/images/social-card.jpg?v='
        in html
    )
    assert 'twitter:card" content="summary_large_image"' in html
    assert "Flood map for any U.S. city or ZIP" in html
    assert "What you can do" in html
    assert "How to use it" in html
    assert "Model notes" in html


def test_homepage_uses_vendored_maplibre_assets(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    resp = client.get("/")

    assert resp.status_code == 200
    html = resp.text
    assert "unpkg.com/maplibre-gl" not in html
    assert "/vendor/maplibre-gl-4.7.1.css" in html
    assert "/vendor/maplibre-gl-csp-4.7.1.js" in html
    assert "/vendor/maplibre-gl-csp-worker-4.7.1.js" in html


def test_social_card_image_is_served_from_root_and_subpath(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_resp = client.get("/static/images/social-card.jpg")
    subpath_resp = client.get("/floodmap/static/images/social-card.jpg")

    assert root_resp.status_code == 200
    assert subpath_resp.status_code == 200
    assert root_resp.headers["content-type"] == "image/jpeg"
    assert subpath_resp.headers["content-type"] == "image/jpeg"
    assert len(root_resp.content) > 1000
    assert len(subpath_resp.content) > 1000
    assert root_resp.content.startswith(b"\xff\xd8\xff")
    assert subpath_resp.content.startswith(b"\xff\xd8\xff")


def test_vendored_maplibre_assets_are_served_from_root_and_subpath(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_css = client.get("/static/vendor/maplibre-gl-4.7.1.css")
    subpath_css = client.get("/floodmap/static/vendor/maplibre-gl-4.7.1.css")
    root_js = client.get("/static/vendor/maplibre-gl-csp-4.7.1.js")
    subpath_js = client.get("/floodmap/static/vendor/maplibre-gl-csp-4.7.1.js")
    root_worker = client.get("/static/vendor/maplibre-gl-csp-worker-4.7.1.js")
    subpath_worker = client.get(
        "/floodmap/static/vendor/maplibre-gl-csp-worker-4.7.1.js"
    )

    assert root_css.status_code == 200
    assert subpath_css.status_code == 200
    assert root_js.status_code == 200
    assert subpath_js.status_code == 200
    assert root_worker.status_code == 200
    assert subpath_worker.status_code == 200
    assert "css" in root_css.headers["content-type"]
    assert "css" in subpath_css.headers["content-type"]
    assert "javascript" in root_js.headers["content-type"]
    assert "javascript" in subpath_js.headers["content-type"]
    assert root_js.headers["content-encoding"] == "gzip"
    assert subpath_js.headers["content-encoding"] == "gzip"
    assert root_worker.headers["content-encoding"] == "gzip"
    assert subpath_worker.headers["content-encoding"] == "gzip"
    assert root_css.content.startswith(b".maplibregl-map")
    assert subpath_css.content.startswith(b".maplibregl-map")
    assert len(root_js.content) > 100000
    assert len(subpath_js.content) > 100000
    assert len(root_worker.content) > 50000
    assert len(subpath_worker.content) > 50000

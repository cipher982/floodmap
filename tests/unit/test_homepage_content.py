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
    assert "FloodMap USA | Search ZIP Codes, Cities, Elevation & Flood Risk" in html
    assert "Interactive U.S. flood map for any city or ZIP code." in html
    assert (
        'og:image" content="https://drose.io/floodmap/static/images/social-card.jpg?v=20260410d"'
        in html
    )
    assert 'twitter:card" content="summary_large_image"' in html
    assert "Flood map for any U.S. city or ZIP" in html
    assert "What you can do" in html
    assert "How to use it" in html
    assert "Model notes" in html


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

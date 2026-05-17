from __future__ import annotations

import importlib
import json
import sys

from fastapi.testclient import TestClient


def load_main_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("main", None)
    sys.modules.pop("config", None)
    return importlib.import_module("main")


def test_frontend_bootstrap_uses_shared_public_path_helpers(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    resp = client.get("/")

    assert resp.status_code == 200
    html = resp.text
    assert "window.FLOODMAP_PUBLIC_BASE_PATH" in html
    assert "window.floodmapPublicUrl = function floodmapPublicUrl" in html
    assert "window.floodmapApiUrl = function floodmapApiUrl" in html
    assert "window.floodmapAssetUrl = function floodmapAssetUrl" in html
    assert "'/floodmap/static/" not in html
    assert "'/floodmap/api/" not in html


def test_frontend_is_served_from_root_and_floodmap_subpath(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_resp = client.get("/")
    subpath_resp = client.get("/floodmap/")

    assert root_resp.status_code == 200
    assert subpath_resp.status_code == 200
    assert root_resp.text == subpath_resp.text


def test_manifest_is_path_relative_for_root_and_subpath(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_manifest = json.loads(client.get("/site.webmanifest").text)
    subpath_manifest = json.loads(client.get("/floodmap/site.webmanifest").text)

    assert root_manifest == subpath_manifest
    assert root_manifest["start_url"] == "./"
    assert root_manifest["scope"] == "./"
    assert root_manifest["icons"][0]["src"] == "favicon.svg"


def test_favicon_redirects_stay_relative(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_resp = client.get("/favicon.ico", follow_redirects=False)
    subpath_resp = client.get("/floodmap/favicon.ico", follow_redirects=False)

    assert root_resp.status_code in {302, 307}
    assert subpath_resp.status_code in {302, 307}
    assert root_resp.headers["location"] == "favicon.svg"
    assert subpath_resp.headers["location"] == "favicon.svg"

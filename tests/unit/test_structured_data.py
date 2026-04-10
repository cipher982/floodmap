from __future__ import annotations

import importlib
import json
import re
import sys

from fastapi.testclient import TestClient

JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


def load_main_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("main", None)
    return importlib.import_module("main")


def extract_json_ld(html: str) -> dict[str, object]:
    match = JSON_LD_RE.search(html)
    assert match is not None
    return json.loads(match.group(1))


def graph_node(payload: dict[str, object], node_type: str) -> dict[str, object]:
    graph = payload["@graph"]
    return next(node for node in graph if node["@type"] == node_type)


def test_homepage_structured_data_matches_rendered_content(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    html = client.get("/").text
    payload = extract_json_ld(html)
    website = graph_node(payload, "WebSite")
    webpage = graph_node(payload, "WebPage")

    assert website["url"] == "https://drose.io/floodmap"
    assert website["name"] == "FloodMap USA"
    assert webpage["url"] == "https://drose.io/floodmap"
    assert webpage["name"].startswith("FloodMap USA | Search ZIP Codes")
    assert (
        "Interactive U.S. flood map for any city or ZIP code." in webpage["description"]
    )
    assert '"@type":"BreadcrumbList"' not in html


def test_city_page_structured_data_matches_visible_city_content(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    html = client.get("/fl/tampa").text
    payload = extract_json_ld(html)
    webpage = graph_node(payload, "WebPage")
    place = graph_node(payload, "Place")
    breadcrumb = graph_node(payload, "BreadcrumbList")

    assert webpage["url"] == "https://drose.io/floodmap/fl/tampa"
    assert webpage["name"].startswith("Tampa Flood Map")
    assert webpage["about"]["@id"] == "https://drose.io/floodmap/fl/tampa#place"
    assert place["name"] == "Tampa, Florida"
    assert abs(place["geo"]["latitude"] - 27.9449854) < 0.0001
    assert abs(place["geo"]["longitude"] - (-82.4583107)) < 0.0001
    assert breadcrumb["itemListElement"][0]["item"] == "https://drose.io/floodmap"
    assert breadcrumb["itemListElement"][0]["name"] == "FloodMap USA"
    assert breadcrumb["itemListElement"][1]["name"] == "Tampa, Florida"
    assert 'aria-label="Breadcrumb"' in html
    assert '<a href="../..">FloodMap USA</a>' in html

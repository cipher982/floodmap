from __future__ import annotations

import importlib
import sys
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from location_catalog import list_city_pages

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def load_main_module(monkeypatch):
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")

    sys.modules.pop("main", None)
    return importlib.import_module("main")


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text)


def test_sitemap_index_lists_pages_and_city_sitemaps(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    root_resp = client.get("/sitemap.xml")
    subpath_resp = client.get("/floodmap/sitemap.xml")

    assert root_resp.status_code == 200
    assert subpath_resp.status_code == 200
    assert root_resp.text == subpath_resp.text

    root = parse_xml(root_resp.text)
    locs = [
        node.text for node in root.findall("sm:sitemap/sm:loc", namespaces=SITEMAP_NS)
    ]

    assert root.tag.endswith("sitemapindex")
    assert "https://drose.io/floodmap/sitemaps/pages.xml" in locs
    assert "https://drose.io/floodmap/sitemaps/cities.xml" in locs


def test_city_sitemap_lists_curated_city_pages(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    resp = client.get("/sitemaps/cities.xml")

    assert resp.status_code == 200
    root = parse_xml(resp.text)
    locs = [node.text for node in root.findall("sm:url/sm:loc", namespaces=SITEMAP_NS)]

    assert root.tag.endswith("urlset")
    assert len(locs) == len(list_city_pages())
    assert "https://drose.io/floodmap/fl/tampa" in locs
    assert "https://drose.io/floodmap/wa/seattle" in locs


def test_homepage_and_city_pages_expose_internal_city_links(monkeypatch):
    main = load_main_module(monkeypatch)
    client = TestClient(main.app)

    home_html = client.get("/").text
    city_html = client.get("/fl/tampa").text

    assert "Popular city flood maps" in home_html
    assert 'href="/floodmap/fl/tampa"' in home_html
    assert 'href="/floodmap/ny/new-york"' in home_html
    assert "Related city flood maps" in city_html
    assert 'href="/floodmap/fl/miami"' in city_html
    assert 'href="/floodmap/ga/savannah"' in city_html

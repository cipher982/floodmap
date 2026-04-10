from __future__ import annotations

from xml.sax.saxutils import escape

from location_catalog import list_city_pages

SITEMAP_XMLNS = "http://www.sitemaps.org/schemas/sitemap/0.9"
CANONICAL_BASE_URL = "https://drose.io/floodmap"


def _render_xml_document(root_tag: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<{root_tag} xmlns="{SITEMAP_XMLNS}">\n'
        f"{body}\n"
        f"</{root_tag}>"
    )


def build_sitemap_index_xml() -> str:
    sitemap_urls = (
        f"{CANONICAL_BASE_URL}/sitemaps/pages.xml",
        f"{CANONICAL_BASE_URL}/sitemaps/cities.xml",
    )
    body = "\n".join(
        f"  <sitemap><loc>{escape(url)}</loc></sitemap>" for url in sitemap_urls
    )
    return _render_xml_document("sitemapindex", body)


def build_pages_sitemap_xml() -> str:
    body = f"  <url><loc>{escape(CANONICAL_BASE_URL)}</loc></url>"
    return _render_xml_document("urlset", body)


def build_city_sitemap_xml() -> str:
    body = "\n".join(
        f"  <url><loc>{escape(f'https://drose.io{city_page.canonical_path}')}</loc></url>"
        for city_page in list_city_pages()
    )
    return _render_xml_document("urlset", body)

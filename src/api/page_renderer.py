from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Final

from location_catalog import (
    HOME_DEFAULT_VIEW_STATE,
    CityPage,
    list_city_pages,
    list_related_city_pages,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
INDEX_TEMPLATE_PATH = WEB_DIR / "index.html"
INDEX_TEMPLATE = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")

ASSET_VERSION: Final[str] = "20260410h"
SOCIAL_IMAGE_URL: Final[str] = (
    f"https://drose.io/floodmap/static/images/social-card.jpg?v={ASSET_VERSION}"
)
UNRESOLVED_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"__FLOODMAP_[A-Z0-9_]+__")


@dataclass(frozen=True)
class PageRenderContext:
    title: str
    description: str
    canonical_url: str
    h1: str
    header_kicker: str
    breadcrumb_nav_html: str
    about_title: str
    about_intro: str
    feature_items: tuple[str, ...]
    how_to_items: tuple[str, ...]
    model_summary: str
    route_context: dict[str, object]
    robots_meta_html: str = ""
    structured_data_html: str = ""
    nearby_links_html: str = ""


def _render_list_items(items: tuple[str, ...]) -> str:
    return "\n".join(f"                    <li>{escape(item)}</li>" for item in items)


def _render_context_script(route_context: dict[str, object]) -> str:
    return json.dumps(route_context, separators=(",", ":"))


def _render_json_ld(payload: dict[str, object]) -> str:
    json_ld = json.dumps(payload, separators=(",", ":"))
    return f'    <script type="application/ld+json">{json_ld}</script>'


def _build_website_node() -> dict[str, object]:
    return {
        "@type": "WebSite",
        "@id": "https://drose.io/floodmap#website",
        "url": "https://drose.io/floodmap",
        "name": "FloodMap USA",
        "description": (
            "Interactive U.S. flood map for any city or ZIP code. Search a "
            "location, compare elevation, test storm surge or sea-level "
            "scenarios, and share the exact map view."
        ),
        "inLanguage": "en-US",
    }


def _build_home_structured_data(title: str, description: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            _build_website_node(),
            {
                "@type": "WebPage",
                "@id": "https://drose.io/floodmap#webpage",
                "url": "https://drose.io/floodmap",
                "name": title,
                "description": description,
                "isPartOf": {"@id": "https://drose.io/floodmap#website"},
                "inLanguage": "en-US",
            },
        ],
    }
    return _render_json_ld(payload)


def _build_city_breadcrumb_html(city_page: CityPage) -> str:
    full_name = escape(city_page.full_name)
    return (
        '                <nav class="page-breadcrumbs" aria-label="Breadcrumb">\n'
        '                    <ol class="breadcrumb-list">\n'
        '                        <li><a href="../..">FloodMap USA</a></li>\n'
        f"                        <li><span>{full_name}</span></li>\n"
        "                    </ol>\n"
        "                </nav>"
    )


def _build_city_structured_data(
    city_page: CityPage, *, title: str, description: str, about_intro: str
) -> str:
    canonical_url = f"https://drose.io{city_page.canonical_path}"
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            _build_website_node(),
            {
                "@type": "WebPage",
                "@id": f"{canonical_url}#webpage",
                "url": canonical_url,
                "name": title,
                "description": description,
                "isPartOf": {"@id": "https://drose.io/floodmap#website"},
                "breadcrumb": {"@id": f"{canonical_url}#breadcrumb"},
                "about": {"@id": f"{canonical_url}#place"},
                "inLanguage": "en-US",
            },
            {
                "@type": "Place",
                "@id": f"{canonical_url}#place",
                "name": city_page.full_name,
                "description": about_intro,
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": city_page.default_view_state.lat,
                    "longitude": city_page.default_view_state.lng,
                },
                "containedInPlace": {
                    "@type": "AdministrativeArea",
                    "name": city_page.state_name,
                },
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{canonical_url}#breadcrumb",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "FloodMap USA",
                        "item": "https://drose.io/floodmap",
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": city_page.full_name,
                    },
                ],
            },
        ],
    }
    return _render_json_ld(payload)


def _build_location_link_section(
    *,
    title: str,
    intro: str,
    city_pages: tuple[CityPage, ...],
) -> str:
    if not city_pages:
        return ""

    links_html = "\n".join(
        "                    "
        f'<li><a href="{escape(city_page.canonical_path, quote=True)}">'
        f"{escape(city_page.full_name)}</a></li>"
        for city_page in city_pages
    )
    return (
        '                <section class="location-link-section">\n'
        f"                    <h3>{escape(title)}</h3>\n"
        f'                    <p class="location-link-intro">{escape(intro)}</p>\n'
        '                    <ul class="location-link-list">\n'
        f"{links_html}\n"
        "                    </ul>\n"
        "                </section>"
    )


def _render_page(context: PageRenderContext) -> str:
    replacements = {
        "__FLOODMAP_ASSET_VERSION__": escape(ASSET_VERSION, quote=True),
        "__FLOODMAP_SOCIAL_IMAGE_URL__": escape(SOCIAL_IMAGE_URL, quote=True),
        "__FLOODMAP_PAGE_TITLE__": escape(context.title, quote=True),
        "__FLOODMAP_PAGE_DESCRIPTION__": escape(context.description, quote=True),
        "__FLOODMAP_CANONICAL_URL__": escape(context.canonical_url, quote=True),
        "__FLOODMAP_OG_TITLE__": escape(context.title, quote=True),
        "__FLOODMAP_OG_DESCRIPTION__": escape(context.description, quote=True),
        "__FLOODMAP_OG_URL__": escape(context.canonical_url, quote=True),
        "__FLOODMAP_TWITTER_TITLE__": escape(context.title, quote=True),
        "__FLOODMAP_TWITTER_DESCRIPTION__": escape(context.description, quote=True),
        "__FLOODMAP_ROBOTS_META__": context.robots_meta_html,
        "__FLOODMAP_ROUTE_CONTEXT_JSON__": _render_context_script(
            context.route_context
        ),
        "__FLOODMAP_STRUCTURED_DATA__": context.structured_data_html,
        "__FLOODMAP_BREADCRUMB_NAV__": context.breadcrumb_nav_html,
        "__FLOODMAP_PAGE_H1__": escape(context.h1),
        "__FLOODMAP_HEADER_KICKER__": escape(context.header_kicker),
        "__FLOODMAP_ABOUT_TITLE__": escape(context.about_title),
        "__FLOODMAP_ABOUT_INTRO__": escape(context.about_intro),
        "__FLOODMAP_FEATURE_ITEMS__": _render_list_items(context.feature_items),
        "__FLOODMAP_HOW_TO_ITEMS__": _render_list_items(context.how_to_items),
        "__FLOODMAP_MODEL_SUMMARY__": escape(context.model_summary),
        "__FLOODMAP_NEARBY_LINKS_SECTION__": context.nearby_links_html,
    }

    html = INDEX_TEMPLATE
    for token, value in replacements.items():
        html = html.replace(token, value)

    unresolved = sorted(set(UNRESOLVED_TOKEN_RE.findall(html)))
    if unresolved:
        unresolved_str = ", ".join(unresolved)
        raise RuntimeError(f"Unresolved Floodmap template tokens: {unresolved_str}")

    return html


def build_home_page_html() -> str:
    context = PageRenderContext(
        title="FloodMap USA | Search ZIP Codes, Cities, Elevation & Flood Risk",
        description="Interactive U.S. flood map for any city or ZIP code. Search a location, compare elevation, test storm surge or sea-level scenarios, and share the exact map view.",
        canonical_url="https://drose.io/floodmap",
        h1="FloodMap USA",
        header_kicker="Search any U.S. city or ZIP code, compare elevation, and preview flood or sea-level scenarios in a shareable map view.",
        breadcrumb_nav_html="",
        about_title="Flood map for any U.S. city or ZIP",
        about_intro="FloodMap USA is a fast screening tool for exploring elevation and water exposure across the United States. Search a location, inspect terrain, switch to flood mode, and share the exact scenario you are looking at.",
        feature_items=(
            "Jump straight to a city or ZIP code instead of manually panning.",
            "Compare elevation and flood-risk views at the same location.",
            "Test scenarios from high tide through extreme storm surge.",
            "Copy a permalink with the current center, zoom, view mode, and water level.",
        ),
        how_to_items=(
            "Search for a U.S. city or ZIP code, or pan to the area you care about.",
            "Use elevation mode for terrain context, then switch to flood mode to test a scenario.",
            "Click a specific point on the map for a location-based risk sample and share the permalink if you want the same view later.",
        ),
        model_summary="This is a rapid relative-visibility tool built from elevation and map data. It is useful for exploration, communication, and scenario comparison, but it is not a substitute for parcel surveys, FEMA products, insurance decisions, or emergency instructions.",
        route_context={
            "pageType": "home",
            "canonicalPath": "/floodmap",
            "defaultViewState": dict(HOME_DEFAULT_VIEW_STATE),
        },
        structured_data_html=_build_home_structured_data(
            "FloodMap USA | Search ZIP Codes, Cities, Elevation & Flood Risk",
            "Interactive U.S. flood map for any city or ZIP code. Search a location, compare elevation, test storm surge or sea-level scenarios, and share the exact map view.",
        ),
        nearby_links_html=_build_location_link_section(
            title="Popular city flood maps",
            intro="Start with a city landing page if you want location-specific copy, metadata, and a map already centered on a major coastal or river metro.",
            city_pages=list_city_pages(),
        ),
    )
    return _render_page(context)


def build_city_page_html(city_page: CityPage) -> str:
    scenario_label = f"{city_page.default_view_state.water:.1f}m"
    focus = city_page.focus_areas
    full_name = city_page.full_name
    title = f"{city_page.city_name} Flood Map | {city_page.state_name} Elevation & Water Scenarios | FloodMap USA"
    description = f"Interactive flood map for {full_name}. Compare elevation, test a {scenario_label} water scenario, and share a city-centered view."
    about_intro = (
        f"Use this {full_name} flood map to inspect {focus}. "
        f"The page opens directly on {city_page.city_name} instead of making you pan from the national view."
    )
    context = PageRenderContext(
        title=title,
        description=description,
        canonical_url=f"https://drose.io{city_page.canonical_path}",
        h1=f"Flood map for {full_name}",
        header_kicker=(
            f"Start on a {full_name} map view, compare elevation with flood mode, "
            f"and use the default {scenario_label} scenario as a fast screening baseline."
        ),
        breadcrumb_nav_html=_build_city_breadcrumb_html(city_page),
        about_title=f"{city_page.city_name} flood map and elevation view",
        about_intro=about_intro,
        feature_items=(
            f"Open a {city_page.city_name}-centered map instead of manually panning across the U.S.",
            f"Compare elevation and flood scenarios around {focus}.",
            f"Start with a {scenario_label} flood setup, then adjust the slider for milder or more extreme water levels.",
            f"Copy a permalink for the exact {city_page.city_name} scenario you want to share.",
        ),
        how_to_items=(
            f"Start with the default {city_page.city_name} map view and pan toward the shoreline, river, or neighborhood you care about.",
            "Use flood mode for scenario testing, or switch to elevation mode to inspect terrain and relative height differences.",
            "Click a specific point on the map for a location-based risk sample, then copy the permalink if you want the same view later.",
        ),
        model_summary=(
            f"{city_page.local_context} FloodMap USA is a screening tool for exploration and comparison, not a substitute for surveys, FEMA products, insurance decisions, or emergency instructions."
        ),
        route_context={
            "pageType": "city",
            "canonicalPath": city_page.canonical_path,
            "stateSlug": city_page.state_slug,
            "citySlug": city_page.city_slug,
            "locationName": full_name,
            "defaultViewState": city_page.default_view_state.as_dict(),
        },
        structured_data_html=_build_city_structured_data(
            city_page,
            title=title,
            description=description,
            about_intro=about_intro,
        ),
        nearby_links_html=_build_location_link_section(
            title="Related city flood maps",
            intro="Jump to another city page if you want a comparable coastal or river-front metro without going back to the homepage.",
            city_pages=list_related_city_pages(city_page),
        ),
    )
    return _render_page(context)

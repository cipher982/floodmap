from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class FloodmapViewState:
    lat: float
    lng: float
    zoom: float
    view: str = "flood"
    water: float = 3.0

    def as_dict(self) -> dict[str, float | str]:
        return {
            "lat": self.lat,
            "lng": self.lng,
            "zoom": self.zoom,
            "view": self.view,
            "water": self.water,
        }


@dataclass(frozen=True)
class CityPage:
    state_slug: str
    city_slug: str
    city_name: str
    state_name: str
    focus_areas: str
    local_context: str
    default_view_state: FloodmapViewState
    related_city_keys: tuple[tuple[str, str], ...] = ()

    @property
    def full_name(self) -> str:
        return f"{self.city_name}, {self.state_name}"

    @property
    def route_path(self) -> str:
        return f"/{self.state_slug}/{self.city_slug}"

    @property
    def canonical_path(self) -> str:
        return f"/floodmap{self.route_path}"


HOME_DEFAULT_VIEW_STATE: Final[dict[str, float | str]] = {
    "lat": 27.95,
    "lng": -82.46,
    "zoom": 8.0,
    "view": "elevation",
    "water": 1.0,
}


_CITY_PAGES: Final[tuple[CityPage, ...]] = (
    CityPage(
        state_slug="fl",
        city_slug="tampa",
        city_name="Tampa",
        state_name="Florida",
        focus_areas="Tampa Bay, the Hillsborough River corridor, and low-lying shoreline neighborhoods",
        local_context="Around Tampa Bay, a short move inland can change elevation and water exposure quickly.",
        default_view_state=FloodmapViewState(
            lat=27.9449854, lng=-82.4583107, zoom=10.4
        ),
        related_city_keys=(("fl", "miami"), ("ga", "savannah"), ("la", "new-orleans")),
    ),
    CityPage(
        state_slug="fl",
        city_slug="miami",
        city_name="Miami",
        state_name="Florida",
        focus_areas="Biscayne Bay, the barrier-island shoreline, and flat inland neighborhoods",
        local_context="Miami sits on a low coastal plain where bayfront, canal, and inland conditions can diverge fast.",
        default_view_state=FloodmapViewState(
            lat=25.7616798, lng=-80.1917902, zoom=10.3
        ),
        related_city_keys=(("fl", "tampa"), ("ga", "savannah"), ("sc", "charleston")),
    ),
    CityPage(
        state_slug="la",
        city_slug="new-orleans",
        city_name="New Orleans",
        state_name="Louisiana",
        focus_areas="Lake Pontchartrain, the Mississippi River bend, and low-elevation neighborhoods across metro New Orleans",
        local_context="In and around New Orleans, levees, water bodies, and very flat terrain make relative elevation differences especially important.",
        default_view_state=FloodmapViewState(
            lat=29.9510658, lng=-90.0715323, zoom=10.2
        ),
        related_city_keys=(("tx", "houston"), ("fl", "tampa"), ("ga", "savannah")),
    ),
    CityPage(
        state_slug="sc",
        city_slug="charleston",
        city_name="Charleston",
        state_name="South Carolina",
        focus_areas="Charleston Harbor, tidal creeks, and the low-lying peninsula street grid",
        local_context="Charleston combines harbor exposure with marshy low ground, so flood screening benefits from a city-specific starting view.",
        default_view_state=FloodmapViewState(
            lat=32.7764749, lng=-79.9310512, zoom=10.9
        ),
        related_city_keys=(("ga", "savannah"), ("va", "norfolk"), ("fl", "miami")),
    ),
    CityPage(
        state_slug="va",
        city_slug="norfolk",
        city_name="Norfolk",
        state_name="Virginia",
        focus_areas="the Elizabeth River, Hampton Roads shoreline, and low waterside districts",
        local_context="Norfolk's flood picture changes between naval, waterfront, and inland areas because the metro sits close to tidal water on multiple sides.",
        default_view_state=FloodmapViewState(
            lat=36.8507689, lng=-76.2858726, zoom=10.5
        ),
        related_city_keys=(
            ("md", "annapolis"),
            ("ny", "new-york"),
            ("sc", "charleston"),
        ),
    ),
    CityPage(
        state_slug="tx",
        city_slug="houston",
        city_name="Houston",
        state_name="Texas",
        focus_areas="Buffalo Bayou, ship-channel corridors, and flat low-lying neighborhoods around the urban core",
        local_context="Houston is not just a coastal story; bayous and flat terrain across the metro make localized elevation checks useful well inland.",
        default_view_state=FloodmapViewState(lat=29.7604267, lng=-95.3698028, zoom=9.9),
        related_city_keys=(("la", "new-orleans"), ("fl", "tampa"), ("fl", "miami")),
    ),
    CityPage(
        state_slug="ny",
        city_slug="new-york",
        city_name="New York",
        state_name="New York",
        focus_areas="New York Harbor, Lower Manhattan, and waterfront neighborhoods from Brooklyn to Queens",
        local_context="New York combines dense waterfront development, rivers, and harbor exposure, so zoomed-in screening is more useful than a generic national default.",
        default_view_state=FloodmapViewState(
            lat=40.7127281, lng=-74.0060152, zoom=10.1
        ),
        related_city_keys=(("ma", "boston"), ("md", "annapolis"), ("va", "norfolk")),
    ),
    CityPage(
        state_slug="ma",
        city_slug="boston",
        city_name="Boston",
        state_name="Massachusetts",
        focus_areas="Boston Harbor, the Charles River basin, and low waterfront districts around the urban core",
        local_context="Boston's coastline, filled land, and river edges make city-scale elevation context useful before drilling down to a block or parcel.",
        default_view_state=FloodmapViewState(lat=42.3554334, lng=-71.060511, zoom=10.6),
        related_city_keys=(("ny", "new-york"), ("md", "annapolis"), ("va", "norfolk")),
    ),
    CityPage(
        state_slug="ga",
        city_slug="savannah",
        city_name="Savannah",
        state_name="Georgia",
        focus_areas="the Savannah River, marsh edges, and the low coastal plain around the historic core",
        local_context="Savannah sits near tidal water and broad marshland, so small elevation shifts can matter across the metro and the riverfront.",
        default_view_state=FloodmapViewState(lat=32.0808989, lng=-81.091203, zoom=10.8),
        related_city_keys=(("sc", "charleston"), ("fl", "tampa"), ("fl", "miami")),
    ),
    CityPage(
        state_slug="md",
        city_slug="annapolis",
        city_name="Annapolis",
        state_name="Maryland",
        focus_areas="the Severn River, downtown Annapolis, and the Chesapeake shoreline",
        local_context="Annapolis is compact but heavily shaped by tidal water, making a location-specific flood map more useful than a generic regional view.",
        default_view_state=FloodmapViewState(
            lat=38.9784453, lng=-76.4921829, zoom=11.1
        ),
        related_city_keys=(("va", "norfolk"), ("ny", "new-york"), ("ma", "boston")),
    ),
    CityPage(
        state_slug="ca",
        city_slug="san-francisco",
        city_name="San Francisco",
        state_name="California",
        focus_areas="the Bay shoreline, Mission Creek, and low waterfront zones around downtown and SoMa",
        local_context="San Francisco mixes steep terrain with vulnerable waterfront edges, so a city-centered flood view helps separate bluff areas from exposed shoreline.",
        default_view_state=FloodmapViewState(
            lat=37.7792588, lng=-122.4193286, zoom=10.4
        ),
        related_city_keys=(("wa", "seattle"), ("ma", "boston"), ("ny", "new-york")),
    ),
    CityPage(
        state_slug="wa",
        city_slug="seattle",
        city_name="Seattle",
        state_name="Washington",
        focus_areas="Puget Sound, Elliott Bay, and low shoreline areas around downtown and the Duwamish corridor",
        local_context="Seattle's hills create sharp elevation shifts near the shore, which makes city-scale screening useful for comparing waterfront and upland areas.",
        default_view_state=FloodmapViewState(
            lat=47.6038321, lng=-122.3300624, zoom=10.1
        ),
        related_city_keys=(
            ("ca", "san-francisco"),
            ("ma", "boston"),
            ("ny", "new-york"),
        ),
    ),
)

CITY_PAGES_BY_SLUG: Final[dict[tuple[str, str], CityPage]] = {
    (city_page.state_slug, city_page.city_slug): city_page for city_page in _CITY_PAGES
}


def get_city_page(state_slug: str, city_slug: str) -> CityPage | None:
    return CITY_PAGES_BY_SLUG.get((state_slug.casefold(), city_slug.casefold()))


def list_city_pages() -> tuple[CityPage, ...]:
    return _CITY_PAGES


def list_related_city_pages(city_page: CityPage) -> tuple[CityPage, ...]:
    related_pages = []
    for state_slug, city_slug in city_page.related_city_keys:
        related_city = get_city_page(state_slug, city_slug)
        if related_city is not None:
            related_pages.append(related_city)
    return tuple(related_pages)

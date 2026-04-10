"""Place search / geocoding endpoints."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from cachetools import TTLCache
from config import (
    GEOCODER_BASE_URL,
    GEOCODER_CACHE_SIZE,
    GEOCODER_CACHE_TTL_SECONDS,
    GEOCODER_COUNTRYCODES,
    GEOCODER_USER_AGENT,
)
from fastapi import APIRouter, HTTPException, Query
from http_client import get_http_client
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

_QUERY_WHITESPACE_RE = re.compile(r"\s+")
_search_cache: TTLCache[str, list[PlaceSearchResult]] = TTLCache(
    maxsize=GEOCODER_CACHE_SIZE,
    ttl=GEOCODER_CACHE_TTL_SECONDS,
)
_search_cache_lock = asyncio.Lock()


class PlaceBounds(BaseModel):
    south: float
    north: float
    west: float
    east: float


class PlaceSearchResult(BaseModel):
    name: str
    label: str
    latitude: float
    longitude: float
    bounds: PlaceBounds | None = None
    category: str | None = None
    type: str | None = None
    addresstype: str | None = None


class PlaceSearchResponse(BaseModel):
    query: str
    results: list[PlaceSearchResult]


def _normalize_query(query: str) -> str:
    return _QUERY_WHITESPACE_RE.sub(" ", query).strip()


def _get_result_name(payload: dict[str, Any]) -> str:
    address = payload.get("address")
    if isinstance(address, dict):
        for key in (
            "city",
            "town",
            "village",
            "hamlet",
            "municipality",
            "county",
            "state",
            "postcode",
        ):
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    display_name = payload.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.split(",", 1)[0].strip()

    return "Unknown location"


def _parse_bounds(payload: dict[str, Any]) -> PlaceBounds | None:
    raw_bounds = payload.get("boundingbox")
    if not isinstance(raw_bounds, list) or len(raw_bounds) != 4:
        return None

    try:
        south = float(raw_bounds[0])
        north = float(raw_bounds[1])
        west = float(raw_bounds[2])
        east = float(raw_bounds[3])
    except (TypeError, ValueError):
        return None

    return PlaceBounds(south=south, north=north, west=west, east=east)


def _parse_search_result(payload: dict[str, Any]) -> PlaceSearchResult | None:
    display_name = payload.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        return None

    try:
        latitude = float(payload["lat"])
        longitude = float(payload["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    return PlaceSearchResult(
        name=_get_result_name(payload),
        label=display_name.strip(),
        latitude=latitude,
        longitude=longitude,
        bounds=_parse_bounds(payload),
        category=payload.get("category"),
        type=payload.get("type"),
        addresstype=payload.get("addresstype"),
    )


async def _get_cached_results(cache_key: str) -> list[PlaceSearchResult] | None:
    async with _search_cache_lock:
        cached = _search_cache.get(cache_key)
        if cached is None:
            return None
        return [result.model_copy(deep=True) for result in cached]


async def _set_cached_results(
    cache_key: str, results: list[PlaceSearchResult]
) -> list[PlaceSearchResult]:
    stored = [result.model_copy(deep=True) for result in results]
    async with _search_cache_lock:
        _search_cache[cache_key] = stored
    return [result.model_copy(deep=True) for result in stored]


@router.get("/places/search", response_model=PlaceSearchResponse)
async def search_places(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(5, ge=1, le=5),
):
    """Search for a US ZIP code, city, or place name."""
    query = _normalize_query(q)
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Search query is too short")

    cache_key = f"{query.casefold()}::{limit}"
    cached = await _get_cached_results(cache_key)
    if cached is not None:
        return PlaceSearchResponse(query=query, results=cached)

    client = await get_http_client()
    params = {
        "format": "jsonv2",
        "addressdetails": 1,
        "countrycodes": GEOCODER_COUNTRYCODES,
        "limit": limit,
        "q": query,
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": GEOCODER_USER_AGENT,
    }

    try:
        response = await client.get(GEOCODER_BASE_URL, params=params, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Place search provider returned %s for query %r",
            exc.response.status_code,
            query,
        )
        raise HTTPException(
            status_code=502, detail="Location search provider error"
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Place search request failed for query %r: %s", query, exc)
        raise HTTPException(
            status_code=502, detail="Location search is temporarily unavailable"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Place search provider returned invalid JSON for %r", query)
        raise HTTPException(
            status_code=502, detail="Location search provider error"
        ) from exc

    if not isinstance(payload, list):
        logger.warning(
            "Place search provider returned unexpected payload for %r", query
        )
        raise HTTPException(status_code=502, detail="Location search provider error")

    results: list[PlaceSearchResult] = []
    seen: set[tuple[str, float, float]] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        result = _parse_search_result(item)
        if result is None:
            continue

        dedupe_key = (
            result.label.casefold(),
            round(result.latitude, 5),
            round(result.longitude, 5),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(result)

    return PlaceSearchResponse(
        query=query,
        results=await _set_cached_results(cache_key, results),
    )

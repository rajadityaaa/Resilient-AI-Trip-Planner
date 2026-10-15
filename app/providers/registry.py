"""
Provider Registry: Ordered provider chain per kind.

Chain order:
1. Foursquare (only if FOURSQUARE_API_KEY is configured and circuit breaker / daily limit allow)
2. Overpass API (for attractions and restaurants, with circuit breaker)
3. Nominatim / OpenStreetMap nearby search
4. Fallback (mock_hotels.json for hotels, AI-suggested places for attractions/restaurants)

First provider returning usable results wins. Results are cached for 24h (or 10m for empty negative results).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.providers.base import KindType
from app.providers.circuit_breaker import is_circuit_open
from app.providers.foursquare import FoursquarePlacesProvider
from app.tools.cache import cache_get, cache_set
from app.tools.geocode_tools import search_places_nearby
from app.tools.places_tools import get_attractions, get_restaurants

logger = logging.getLogger(__name__)

MOCK_HOTELS_FILE = Path(__file__).parent.parent / "data" / "mock_hotels.json"


def estimate_hotel_pricing(
    hotel: dict,
    budget_total: Optional[float] = None,
    travelers: int = 1,
) -> dict:
    """
    Produce a real listing with an estimated price per night.
    Marks price_source as 'estimated' to ensure honesty.
    """
    price_level = hotel.get("price_level")
    rating = hotel.get("rating")
    star_rating = hotel.get("star_rating")

    if star_rating is None:
        if rating is not None:
            star_rating = round(min(5.0, max(1.0, float(rating) / 2.0)), 1)
        elif price_level is not None:
            star_rating = min(5.0, max(2.0, 1.0 + float(price_level)))
        else:
            star_rating = 4.0

    # Base price estimation by price_level / star_rating
    if price_level == 1:
        base_price = 45.0
    elif price_level == 2:
        base_price = 85.0
    elif price_level == 3:
        base_price = 160.0
    elif price_level == 4:
        base_price = 280.0
    else:
        # Interpolate from star_rating (1.0 to 5.0)
        base_price = 30.0 + (star_rating - 1.0) * 45.0

    # Mild adjustment based on budget if available
    if budget_total and budget_total > 0:
        # E.g. lodging is roughly 30% of total budget across ~3 nights
        suggested_lodging_per_night = (budget_total * 0.30) / max(1, 3)
        # Blend 70% base price + 30% suggested lodging
        estimated_price = round(0.7 * base_price + 0.3 * suggested_lodging_per_night, 2)
    else:
        estimated_price = round(base_price, 2)

    lat = hotel.get("lat") or hotel.get("location_lat")
    lon = hotel.get("lon") or hotel.get("location_lon")

    amenities = hotel.get("amenities") or ["Free WiFi", "Air Conditioning", "24/7 Front Desk"]
    if star_rating >= 4.5 and "Swimming Pool" not in amenities:
        amenities = list(amenities) + ["Swimming Pool", "Fitness Center"]

    return {
        "name": hotel.get("name", "Hotel"),
        "star_rating": float(star_rating),
        "rating": rating,
        "price_level": price_level,
        "price_per_night_usd": float(estimated_price),
        "price_source": "estimated",
        "location_lat": float(lat) if lat is not None else None,
        "location_lon": float(lon) if lon is not None else None,
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "amenities": amenities,
        "website": hotel.get("website"),
        "phone": hotel.get("phone"),
        "address": hotel.get("address"),
        "source": hotel.get("source", "foursquare"),
    }


def search_places(
    kind: KindType,
    lat: float,
    lon: float,
    radius_m: int = 5000,
    limit: int = 15,
    query: Optional[str] = None,
    destination: Optional[str] = None,
    budget_total: Optional[float] = None,
) -> tuple[list[dict], str]:
    """
    Search places following the ordered provider chain:
    1. Foursquare (if configured and available)
    2. Overpass (for attractions and restaurants)
    3. Nominatim (box search)
    4. Mock/Fallback data

    Returns (places_list, winning_provider_name).
    Results are cached for 24h (or 10m for empty results).
    """
    cache_key = f"places_chain:{kind}:{lat:.4f}:{lon:.4f}:{radius_m}:{limit}:{query or ''}"
    cached = cache_get(cache_key)
    if cached is not None:
        source = cached[0].get("source", "cache") if cached else "negative_cache"
        return cached, source

    # ── 1. Foursquare ─────────────────────────────────────────────────────────
    fs_provider = FoursquarePlacesProvider()
    if fs_provider.is_configured() and not is_circuit_open(fs_provider.name):
        try:
            fs_results = fs_provider.search(
                kind=kind,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                limit=limit,
                query=query,
            )
            if fs_results:
                if kind == "hotels":
                    fs_results = [
                        estimate_hotel_pricing(h, budget_total=budget_total)
                        for h in fs_results
                    ]
                cache_set(cache_key, fs_results, ttl_seconds=86400)
                return fs_results, "foursquare"
        except Exception as exc:
            logger.warning(f"[ProviderRegistry] Foursquare search failed: {exc}")

    # ── 2. Overpass API ───────────────────────────────────────────────────────
    if kind == "attractions":
        try:
            osm_results = get_attractions(lat=lat, lon=lon, radius_m=radius_m, limit=limit)
            if osm_results:
                cache_set(cache_key, osm_results, ttl_seconds=86400)
                return osm_results, "osm"
        except Exception as exc:
            logger.warning(f"[ProviderRegistry] Overpass attractions failed: {exc}")

    elif kind == "restaurants":
        try:
            osm_results = get_restaurants(
                lat=lat, lon=lon, radius_m=radius_m, cuisine=query, limit=limit
            )
            if osm_results:
                cache_set(cache_key, osm_results, ttl_seconds=86400)
                return osm_results, "osm"
        except Exception as exc:
            logger.warning(f"[ProviderRegistry] Overpass restaurants failed: {exc}")

    # ── 3. Nominatim search ───────────────────────────────────────────────────
    nom_results = _search_nominatim(kind, lat, lon, query, limit)
    if nom_results:
        if kind == "hotels":
            nom_results = [
                estimate_hotel_pricing(h, budget_total=budget_total)
                for h in nom_results
            ]
        cache_set(cache_key, nom_results, ttl_seconds=86400)
        return nom_results, "nominatim"

    # ── 4. Mock dataset (hotels only) ─────────────────────────────────────────
    if kind == "hotels" and destination:
        mock_results = _get_mock_hotels(destination)
        if mock_results:
            cache_set(cache_key, mock_results, ttl_seconds=86400)
            return mock_results, "mock_data"

    # Negative caching for 10 minutes
    cache_set(cache_key, [], ttl_seconds=600)
    return [], "none"


def _search_nominatim(
    kind: KindType, lat: float, lon: float, query: Optional[str], limit: int
) -> list[dict]:
    """Fallback search using Nominatim bounding box search."""
    if kind == "attractions":
        queries, delta = ["tourist attraction", "museum", "temple", "park"], 0.05
    elif kind == "restaurants":
        queries = [query] if query else ["restaurant", "cafe"]
        delta = 0.025
    else:
        queries, delta = ["hotel", "hostel", "guest house"], 0.04

    out, seen = [], set()
    for q in queries:
        try:
            for it in search_places_nearby(q, lat, lon, delta=delta, limit=limit):
                name = it.get("name", "").strip()
                if not name or name.lower() in seen:
                    continue
                seen.add(name.lower())
                cat = (it.get("type") or q).replace("_", " ").capitalize()
                out.append({
                    "name": name,
                    "category": cat,
                    "lat": float(it["lat"]),
                    "lon": float(it["lon"]),
                    "address": it.get("display_name", ""),
                    "source": "nominatim",
                    "tags": {},
                })
                if len(out) >= limit:
                    return out
        except Exception as exc:
            logger.debug(f"[Nominatim Fallback] Query '{q}' failed: {exc}")

    return out[:limit]


def _get_mock_hotels(destination: str) -> list[dict]:
    """Look up matching hotels from app/data/mock_hotels.json."""
    if not MOCK_HOTELS_FILE.exists():
        return []
    dest_city = destination.split(",")[0].strip().lower()
    try:
        with open(MOCK_HOTELS_FILE, "r", encoding="utf-8") as f:
            dataset = json.load(f)
        matched = []
        for h in dataset:
            city_val = h.get("city", "").lower()
            if dest_city in city_val or city_val in dest_city:
                item = dict(h)
                item["source"] = "mock_data"
                item["price_source"] = "estimated"
                item["lat"] = item.get("location_lat")
                item["lon"] = item.get("location_lon")
                matched.append(item)
        return matched
    except Exception as exc:
        logger.warning(f"[MockHotels] Failed to read mock hotels: {exc}")
        return []

"""
Places Tools: Overpass API wrapper for fetching attractions and restaurants with retry,
circuit breaker integration, and TTL + negative caching.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from app.providers.circuit_breaker import (
    is_circuit_open,
    record_failure,
    record_success,
)
from app.tools.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def _post_one(target: str, query: str, timeout: float) -> Optional[dict]:
    headers = {"User-Agent": "TravelPlannerAgent/1.0 (contact@travelplanner.app)"}
    try:
        response = requests.post(target, data={"data": query}, headers=headers, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        logger.warning(f"[Overpass Tool] {target} returned status {response.status_code}")
    except Exception as err:
        logger.warning(f"[Overpass Tool] {target} failed: {err}")
    return None


def _fetch_overpass_with_retry(
    query: str, attempts: int = 1, url: str = OVERPASS_URL, timeout: float = 6
) -> Optional[dict]:
    """
    Race ALL Overpass mirrors at the same time; the first valid answer wins.
    If the circuit breaker for 'overpass' is OPEN, skips mirrors immediately.
    If all mirrors fail, trips the circuit breaker for 5 minutes.
    """
    if is_circuit_open("overpass"):
        logger.info("[Overpass Tool] Circuit breaker is OPEN. Skipping Overpass mirrors.")
        return None

    pool = ThreadPoolExecutor(max_workers=len(OVERPASS_MIRRORS))
    futures = [pool.submit(_post_one, m, query, timeout) for m in OVERPASS_MIRRORS]
    try:
        for fut in as_completed(futures, timeout=timeout + 1):
            res = fut.result()
            if res and "elements" in res:
                record_success("overpass")
                return res
    except Exception:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    logger.error("[Overpass Tool] All mirrors failed for query.")
    # Trip circuit breaker for 5 minutes (300 seconds)
    record_failure("overpass", force_trip=True, cooldown_s=300)
    return None


def _parse_elements(elements: list, limit: int, category_fn, cuisine_norm: Optional[str] = None) -> list:
    results, seen_names = [], set()
    for item in elements:
        tags = item.get("tags", {})
        name = tags.get("name", "").strip()
        if not name or name.lower() in seen_names:
            continue
        item_lat = item.get("lat") or item.get("center", {}).get("lat")
        item_lon = item.get("lon") or item.get("center", {}).get("lon")
        if item_lat is None or item_lon is None:
            continue
        if cuisine_norm and cuisine_norm not in tags.get("cuisine", "").lower():
            continue
        seen_names.add(name.lower())
        results.append({
            "name": name,
            "category": category_fn(tags),
            "lat": float(item_lat),
            "lon": float(item_lon),
            "tags": tags,
            "source": "osm",
        })
        if len(results) >= limit:
            break
    return results


def _attraction_category(tags: dict) -> str:
    if "tourism" in tags:
        return tags["tourism"].capitalize()
    if "historic" in tags:
        return "Historic"
    if "leisure" in tags:
        return tags["leisure"].capitalize()
    return "Attraction"


def get_attractions(lat: float, lon: float, radius_m: int = 5000, limit: int = 15) -> list[dict]:
    """
    Fetch top attractions within radius_m of (lat, lon).
    Cached for 24h on success; empty results negatively cached for 10 min.
    """
    cache_key = f"attractions:{lat:.4f}:{lon:.4f}:{radius_m}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    around = f"(around:{radius_m},{lat},{lon})"
    notable = f"""
    [out:json][timeout:6];
    (
      nwr["tourism"~"^(attraction|museum|gallery|viewpoint|zoo|theme_park)$"]["name"]["wikidata"]{around};
      nwr["historic"]["name"]["wikidata"]{around};
      nwr["leisure"="park"]["name"]["wikidata"]{around};
    );
    out center 80;
    """
    broad = f"""
    [out:json][timeout:6];
    (
      nwr["tourism"~"^(attraction|museum|gallery|viewpoint)$"]["name"]{around};
      nwr["historic"]["name"]{around};
      nwr["leisure"="park"]["name"]{around};
    );
    out center 60;
    """

    results = []
    data = _fetch_overpass_with_retry(notable)
    if data and "elements" in data:
        results = _parse_elements(data["elements"], limit, _attraction_category)

    if len(results) < 6 and not is_circuit_open("overpass"):
        data2 = _fetch_overpass_with_retry(broad, attempts=1)
        if data2 and "elements" in data2:
            extra = _parse_elements(data2["elements"], limit, _attraction_category)
            have = {r["name"].lower() for r in results}
            results += [e for e in extra if e["name"].lower() not in have]
            results = results[:limit]

    if results:
        cache_set(cache_key, results, ttl_seconds=86400)
    else:
        # Negative caching for 10 minutes (600 seconds)
        cache_set(cache_key, [], ttl_seconds=600)

    return results


def get_restaurants(
    lat: float,
    lon: float,
    radius_m: int = 3000,
    cuisine: Optional[str] = None,
    limit: int = 15,
) -> list[dict]:
    """
    Fetch restaurants/cafes within radius_m of (lat, lon).
    Cached for 24h on success; empty results negatively cached for 10 min.
    """
    cuisine_norm = cuisine.strip().lower() if cuisine else None
    cache_key = f"restaurants:{lat:.4f}:{lon:.4f}:{radius_m}:{cuisine_norm}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    around = f"(around:{radius_m},{lat},{lon})"
    notable = f"""
    [out:json][timeout:6];
    (
      nwr["amenity"="restaurant"]["name"]["cuisine"]{around};
      nwr["amenity"="cafe"]["name"]["cuisine"]{around};
    );
    out center 80;
    """
    broad = f"""
    [out:json][timeout:6];
    (
      nwr["amenity"="restaurant"]["name"]{around};
      nwr["amenity"="cafe"]["name"]{around};
    );
    out center 60;
    """

    results = []
    data = _fetch_overpass_with_retry(notable)
    if data and "elements" in data:
        results = _parse_elements(data["elements"], limit, lambda tags: tags.get("cuisine", "Restaurant").capitalize(), cuisine_norm)

    if len(results) < 6 and not is_circuit_open("overpass"):
        data2 = _fetch_overpass_with_retry(broad, attempts=1)
        if data2 and "elements" in data2:
            extra = _parse_elements(data2["elements"], limit, lambda tags: tags.get("amenity", "Restaurant").capitalize(), None)
            have = {r["name"].lower() for r in results}
            results += [e for e in extra if e["name"].lower() not in have]
            results = results[:limit]

    if results:
        cache_set(cache_key, results, ttl_seconds=86400)
    else:
        # Negative caching for 10 minutes (600 seconds)
        cache_set(cache_key, [], ttl_seconds=600)

    return results

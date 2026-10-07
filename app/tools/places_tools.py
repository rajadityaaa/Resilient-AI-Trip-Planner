"""
Places Tools: Overpass API wrapper for fetching attractions and restaurants with retry and TTL caching.
"""
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
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


def _fetch_overpass_with_retry(query: str, attempts: int = 1, url: str = OVERPASS_URL, timeout: float = 16) -> Optional[dict]:
    """
    Race ALL Overpass mirrors at the same time; the first valid answer wins.
    A slow/overloaded public server no longer blocks us - total wait is at most `timeout` seconds.
    (`attempts`/`url` kept for backward compatibility.)
    """
    pool = ThreadPoolExecutor(max_workers=len(OVERPASS_MIRRORS))
    futures = [pool.submit(_post_one, m, query, timeout) for m in OVERPASS_MIRRORS]
    try:
        for fut in as_completed(futures, timeout=timeout + 2):
            res = fut.result()
            if res and "elements" in res:
                return res
    except Exception:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    logger.error("[Overpass Tool] All mirrors failed for query.")
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

    Two-tier strategy so big cities (London, Paris...) don't time out:
      1. Notable places only (named + wikidata tag) - small, fast, and the places tourists actually want.
      2. If that returns too few (small towns), fall back to a broader named-places query.
    Output is capped server-side (`out center N`) so the response stays small.
    """
    cache_key = f"attractions:{lat:.4f}:{lon:.4f}:{radius_m}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    around = f"(around:{radius_m},{lat},{lon})"
    notable = f"""
    [out:json][timeout:15];
    (
      nwr["tourism"~"^(attraction|museum|gallery|viewpoint|zoo|theme_park)$"]["name"]["wikidata"]{around};
      nwr["historic"]["name"]["wikidata"]{around};
      nwr["leisure"="park"]["name"]["wikidata"]{around};
    );
    out center 80;
    """
    broad = f"""
    [out:json][timeout:15];
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

    if len(results) < 6:
        data2 = _fetch_overpass_with_retry(broad, attempts=1)
        if data2 and "elements" in data2:
            extra = _parse_elements(data2["elements"], limit, _attraction_category)
            have = {r["name"].lower() for r in results}
            results += [e for e in extra if e["name"].lower() not in have]
            results = results[:limit]

    if results:
        cache_set(cache_key, results, ttl_seconds=86400)
    return results


def get_restaurants(
    lat: float,
    lon: float,
    radius_m: int = 3000,
    cuisine: Optional[str] = None,
    limit: int = 15
) -> list[dict]:
    """
    Fetch restaurants/cafes within radius_m of (lat, lon).
    Prefers places that have a cuisine tag (higher quality data, smaller response);
    falls back to any named restaurant if that returns too few. Output capped with `out center N`.
    """
    cuisine_norm = cuisine.strip().lower() if cuisine else None
    cache_key = f"restaurants:{lat:.4f}:{lon:.4f}:{radius_m}:{cuisine_norm}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    around = f"(around:{radius_m},{lat},{lon})"
    cuisine_filter = f'["cuisine"~"{cuisine_norm}",i]' if cuisine_norm else '["cuisine"]'
    tier1 = f"""
    [out:json][timeout:15];
    (
      nwr["amenity"~"^(restaurant|cafe)$"]["name"]{cuisine_filter}{around};
    );
    out center 60;
    """
    tier2 = f"""
    [out:json][timeout:15];
    (
      nwr["amenity"~"^(restaurant|cafe|fast_food)$"]["name"]{around};
    );
    out center 40;
    """
    cat = lambda t: t.get("amenity", "restaurant").capitalize()

    results = []
    data = _fetch_overpass_with_retry(tier1)
    if data and "elements" in data:
        results = _parse_elements(data["elements"], limit, cat)

    # Only broaden when the user did NOT ask for a specific cuisine (agent handles that fallback itself)
    if len(results) < 6 and not cuisine_norm:
        data2 = _fetch_overpass_with_retry(tier2, attempts=1)
        if data2 and "elements" in data2:
            extra = _parse_elements(data2["elements"], limit, cat)
            have = {r["name"].lower() for r in results}
            results += [e for e in extra if e["name"].lower() not in have]
            results = results[:limit]

    if results:
        cache_set(cache_key, results, ttl_seconds=86400)
    return results

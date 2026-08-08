"""
Places Tools: Overpass API wrapper for fetching attractions and restaurants with retry and TTL caching.
"""
import time
import logging
import requests
from typing import Optional
from app.tools.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _fetch_overpass_with_retry(query: str, attempts: int = 3, url: str = OVERPASS_URL) -> Optional[dict]:
    """
    Execute Overpass query with exponential backoff retries (sleep 2s, 4s, 8s).

    Args:
        query: Overpass QL query string.
        attempts: Maximum retry attempts.
        url: Overpass endpoint URL.

    Returns:
        Optional[dict]: Parsed JSON response or None if all attempts fail.
    """
    backoff_delays = [2, 4, 8]
    for attempt in range(attempts):
        try:
            headers = {"User-Agent": "TravelPlannerAgent/1.0 (contact@travelplanner.app)"}
            response = requests.post(url, data={"data": query}, headers=headers, timeout=25)
            if response.status_code == 200:
                return response.json()
            logger.warning(
                f"[Overpass Tool] Attempt {attempt + 1}/{attempts} returned status {response.status_code}"
            )
        except Exception as err:
            logger.warning(
                f"[Overpass Tool] Attempt {attempt + 1}/{attempts} failed with error: {err}"
            )

        if attempt < attempts - 1:
            sleep_sec = backoff_delays[attempt] if attempt < len(backoff_delays) else 8
            time.sleep(sleep_sec)

    logger.error(f"[Overpass Tool] All {attempts} attempts failed for query.")
    return None


def get_attractions(lat: float, lon: float, radius_m: int = 5000, limit: int = 15) -> list[dict]:
    """
    Fetch top attractions (sights, museums, historic sites, parks) within radius_m of (lat, lon).

    Args:
        lat: Latitude coordinate.
        lon: Longitude coordinate.
        radius_m: Search radius in meters (default 5000m).
        limit: Max number of deduplicated results (default 15).

    Returns:
        list[dict]: List of {"name", "category", "lat", "lon", "tags"}.
    """
    cache_key = f"attractions:{lat:.4f}:{lon:.4f}:{radius_m}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = f"""
    [out:json][timeout:25];
    (
      node["tourism"="attraction"](around:{radius_m},{lat},{lon});
      way["tourism"="attraction"](around:{radius_m},{lat},{lon});
      node["tourism"="museum"](around:{radius_m},{lat},{lon});
      way["tourism"="museum"](around:{radius_m},{lat},{lon});
      node["historic"](around:{radius_m},{lat},{lon});
      way["historic"](around:{radius_m},{lat},{lon});
      node["leisure"="park"](around:{radius_m},{lat},{lon});
      way["leisure"="park"](around:{radius_m},{lat},{lon});
    );
    out center body;
    """

    data = _fetch_overpass_with_retry(query)
    if not data or "elements" not in data:
        return []

    elements = data.get("elements", [])
    results = []
    seen_names = set()

    for item in elements:
        tags = item.get("tags", {})
        name = tags.get("name", "").strip()
        if not name or name.lower() in seen_names:
            continue

        item_lat = item.get("lat") or item.get("center", {}).get("lat")
        item_lon = item.get("lon") or item.get("center", {}).get("lon")

        if item_lat is None or item_lon is None:
            continue

        category = "Attraction"
        if "tourism" in tags:
            category = tags["tourism"].capitalize()
        elif "historic" in tags:
            category = "Historic"
        elif "leisure" in tags:
            category = tags["leisure"].capitalize()

        seen_names.add(name.lower())
        results.append({
            "name": name,
            "category": category,
            "lat": float(item_lat),
            "lon": float(item_lon),
            "tags": tags
        })

        if len(results) >= limit:
            break

    # Cache results with 24-hour TTL (86,400 seconds)
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
    Fetch restaurant and cafe recommendations within radius_m of (lat, lon).

    Args:
        lat: Latitude coordinate.
        lon: Longitude coordinate.
        radius_m: Search radius in meters (default 3000m).
        cuisine: Optional cuisine filter string (e.g. "italian", "indian").
        limit: Max number of deduplicated results (default 15).

    Returns:
        list[dict]: List of {"name", "category", "lat", "lon", "tags"}.
    """
    cuisine_norm = cuisine.strip().lower() if cuisine else None
    cache_key = f"restaurants:{lat:.4f}:{lon:.4f}:{radius_m}:{cuisine_norm}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="restaurant"](around:{radius_m},{lat},{lon});
      way["amenity"="restaurant"](around:{radius_m},{lat},{lon});
      node["amenity"="cafe"](around:{radius_m},{lat},{lon});
      way["amenity"="cafe"](around:{radius_m},{lat},{lon});
      node["amenity"="fast_food"](around:{radius_m},{lat},{lon});
      way["amenity"="fast_food"](around:{radius_m},{lat},{lon});
    );
    out center body;
    """

    data = _fetch_overpass_with_retry(query)
    if not data or "elements" not in data:
        return []

    elements = data.get("elements", [])
    results = []
    seen_names = set()

    for item in elements:
        tags = item.get("tags", {})
        name = tags.get("name", "").strip()
        if not name or name.lower() in seen_names:
            continue

        item_lat = item.get("lat") or item.get("center", {}).get("lat")
        item_lon = item.get("lon") or item.get("center", {}).get("lon")

        if item_lat is None or item_lon is None:
            continue

        # Client-side cuisine filtering if requested
        if cuisine_norm:
            tag_cuisine = tags.get("cuisine", "").lower()
            if cuisine_norm not in tag_cuisine:
                continue

        category = tags.get("amenity", "restaurant").capitalize()

        seen_names.add(name.lower())
        results.append({
            "name": name,
            "category": category,
            "lat": float(item_lat),
            "lon": float(item_lon),
            "tags": tags
        })

        if len(results) >= limit:
            break

    # Cache results with 24-hour TTL (86,400 seconds)
    cache_set(cache_key, results, ttl_seconds=86400)
    return results

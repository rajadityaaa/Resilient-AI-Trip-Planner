"""
Geocoding Tools: Nominatim OpenStreetMap wrapper with rate-limiting and TTL caching.
"""
import time
import requests
from typing import Optional
from app.tools.cache import cache_get, cache_set

_LAST_CALL_TIMESTAMP: float = 0.0


class GeocodeNotFoundError(Exception):
    """Raised when a place cannot be geocoded by Nominatim."""
    pass


def geocode_place(place_name: str) -> dict:
    """
    Geocode a place name into latitude, longitude, display name, country, and bounding box.

    Enforces:
    - 30-day TTL cache via cache.py
    - Hard minimum 1-second delay between outgoing API requests
    - Descriptive User-Agent header required by Nominatim usage policy

    Args:
        place_name: Location query string (e.g. "Jaipur, India").

    Returns:
        dict: {
            "lat": float,
            "lon": float,
            "display_name": str,
            "country": str,
            "bounding_box": list[float]
        }

    Raises:
        GeocodeNotFoundError: If place cannot be found or API request fails.
    """
    if not place_name or not place_name.strip():
        raise GeocodeNotFoundError("Place name cannot be empty.")

    clean_name = place_name.strip().lower()
    cache_key = f"geocode:{clean_name}"

    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # Enforce minimum 1-second gap between network API requests
    global _LAST_CALL_TIMESTAMP
    elapsed = time.time() - _LAST_CALL_TIMESTAMP
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "TravelPlannerAgent/1.0 (contact@travelplanner.app)",
        "Accept-Language": "en"
    }
    params = {
        "q": place_name.strip(),
        "format": "json",
        "addressdetails": 1,
        "accept-language": "en",
        "limit": 1
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        _LAST_CALL_TIMESTAMP = time.time()
        response.raise_for_status()
        data = response.json()
    except Exception as err:
        _LAST_CALL_TIMESTAMP = time.time()
        raise GeocodeNotFoundError(f"Failed to geocode '{place_name}': {err}") from err

    if not data or not isinstance(data, list):
        raise GeocodeNotFoundError(f"No geocoding results found for '{place_name}'.")

    item = data[0]
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
        display_name = item.get("display_name", "")
        address = item.get("address", {})
        country = address.get("country", "")
        if not country and display_name:
            country = display_name.split(",")[-1].strip()

        raw_bbox = item.get("boundingbox", [])
        bounding_box = [float(val) for val in raw_bbox]

        result = {
            "lat": lat,
            "lon": lon,
            "display_name": display_name,
            "country": country,
            "bounding_box": bounding_box
        }
    except (KeyError, ValueError, TypeError) as err:
        raise GeocodeNotFoundError(f"Invalid coordinate payload for '{place_name}': {err}") from err

    # Cache result for 30 days (2,592,000 seconds)
    cache_set(cache_key, result, ttl_seconds=30 * 86400)
    return result


def search_places_nearby(query: str, lat: float, lon: float, delta: float = 0.04, limit: int = 20) -> list:
    """
    Nominatim search restricted to a bounding box around (lat, lon). Used as a reliable,
    LLM-independent fallback source of real named places (restaurants, museums, attractions...).

    Returns list of {"name", "lat", "lon", "type"}. Never raises (returns [] on failure).
    """
    cache_key = f"nearby:{query}:{lat:.3f}:{lon:.3f}:{delta}:{limit}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    global _LAST_CALL_TIMESTAMP
    elapsed = time.time() - _LAST_CALL_TIMESTAMP
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": limit,
        "bounded": 1,
        "viewbox": f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}",
        "accept-language": "en",
    }
    headers = {"User-Agent": "TravelPlannerAgent/1.0 (contact@travelplanner.app)", "Accept-Language": "en"}
    out, seen = [], set()
    try:
        resp = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers, timeout=10)
        _LAST_CALL_TIMESTAMP = time.time()
        resp.raise_for_status()
        for it in resp.json():
            name = (it.get("name") or it.get("display_name", "").split(",")[0]).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({"name": name, "lat": float(it["lat"]), "lon": float(it["lon"]), "type": it.get("type", "")})
    except Exception:
        _LAST_CALL_TIMESTAMP = time.time()
        return []

    if out:
        cache_set(cache_key, out, ttl_seconds=86400)
    return out

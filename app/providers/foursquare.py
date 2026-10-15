"""
Foursquare Places API provider implementation.

Specifications (Official Foursquare Places API):
- Base URL: https://places-api.foursquare.com/places/search (fallback https://api.foursquare.com/v3/places/search)
- Auth Header: Authorization: Bearer <API_KEY>
- Version Header: X-Places-Api-Version: 2025-06-17
- Accept: application/json
- Timeout: 8s, 1 retry on 5xx / timeouts
- Requested fields: fsq_id,name,geocodes,location,categories,rating,price,website,tel
- Resilience: circuit breaker integration + SQLite-backed daily budget counter.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from app.providers.base import KindType, PlacesProvider
from app.providers.circuit_breaker import is_circuit_open, record_failure, record_success
from app.tools.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

PRIMARY_SEARCH_URL = "https://places-api.foursquare.com/places/search"
FALLBACK_SEARCH_URL = "https://api.foursquare.com/v3/places/search"
API_VERSION = "2025-06-17"
DEFAULT_TIMEOUT_S = 8.0
DEFAULT_DAILY_LIMIT = 200

# Foursquare taxonomy category IDs
CATEGORY_MAP: dict[KindType, str] = {
    "attractions": "16000,10000",   # Landmarks & Outdoors, Arts & Entertainment
    "restaurants": "13000",         # Dining and Drinking
    "hotels": "19014",              # Hotel
}


# ── Daily call budget counter (persisted in SQLite cache) ─────────────────────

def get_daily_calls() -> int:
    """Get the number of Foursquare API calls made today (UTC)."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    val = cache_get(f"budget:foursquare:{today_str}")
    try:
        return int(val) if val is not None else 0
    except (ValueError, TypeError):
        return 0


def increment_daily_calls() -> int:
    """Increment today's Foursquare API call count."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    current = get_daily_calls() + 1
    # Cache for 48 hours to cleanly cover UTC transitions
    cache_set(f"budget:foursquare:{today_str}", current, ttl_seconds=86400 * 2)
    return current


def is_daily_limit_reached() -> bool:
    """Check if the daily limit has been reached."""
    limit_str = os.getenv("FOURSQUARE_DAILY_LIMIT", str(DEFAULT_DAILY_LIMIT))
    try:
        limit = int(limit_str)
    except ValueError:
        limit = DEFAULT_DAILY_LIMIT
    return get_daily_calls() >= limit


def reset_daily_calls() -> None:
    """Reset today's call counter (for tests)."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_set(f"budget:foursquare:{today_str}", 0, ttl_seconds=86400 * 2)


# ── Provider Implementation ───────────────────────────────────────────────────

class FoursquarePlacesProvider:
    name: str = "foursquare"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("FOURSQUARE_API_KEY", "").strip()

    def is_configured(self) -> bool:
        """Return True if an API key is present."""
        return bool(self.api_key or os.getenv("FOURSQUARE_API_KEY", "").strip())

    def _get_api_key(self) -> str:
        return self.api_key or os.getenv("FOURSQUARE_API_KEY", "").strip()

    def search(
        self,
        kind: KindType,
        lat: float,
        lon: float,
        radius_m: int,
        limit: int,
        query: Optional[str] = None,
    ) -> list[dict]:
        """
        Execute search against Foursquare Places API.
        Respects circuit breaker and daily call limits.
        Retries once on 5xx errors or timeouts.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.debug("[Foursquare] Skipped: no FOURSQUARE_API_KEY configured.")
            return []

        if is_daily_limit_reached():
            logger.warning("[Foursquare] Skipped: daily call limit reached.")
            return []

        if is_circuit_open(self.name):
            logger.warning("[Foursquare] Skipped: circuit breaker is OPEN (cooldown).")
            return []

        auth_header = api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}"
        headers = {
            "Authorization": auth_header,
            "X-Places-Api-Version": API_VERSION,
            "Accept": "application/json",
            "User-Agent": "TravelPlannerAgent/1.0",
        }

        params: dict[str, str | int] = {
            "ll": f"{lat:.6f},{lon:.6f}",
            "radius": radius_m,
            "limit": min(limit, 50),
            "fields": "fsq_id,name,geocodes,location,categories,rating,price,website,tel",
        }

        # Categories filter
        cat_ids = CATEGORY_MAP.get(kind)
        if cat_ids:
            params["fsq_category_ids"] = cat_ids

        if query:
            params["query"] = query

        data = self._make_request_with_retry(headers, params)
        if data is None:
            return []

        results = self._parse_results(data, kind)
        return results

    def _make_request_with_retry(
        self, headers: dict[str, str], params: dict[str, str | int]
    ) -> Optional[dict]:
        """
        Send GET request with 1 retry on 5xx or timeout.
        Updates circuit breaker and daily budget.
        """
        url = PRIMARY_SEARCH_URL
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            try:
                increment_daily_calls()
                resp = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT_S)

                # 200 OK -> Success
                if resp.status_code == 200:
                    record_success(self.name)
                    return resp.json()

                # 401 Unauthorized / 403 Forbidden / 429 Too Many Requests
                if resp.status_code in (401, 403, 429):
                    logger.warning(f"[Foursquare] HTTP {resp.status_code}: {resp.text[:200]}")
                    record_failure(self.name)
                    return None

                # 5xx Server Error -> retry once
                if resp.status_code >= 500:
                    logger.warning(f"[Foursquare] HTTP {resp.status_code} on attempt {attempt}: {resp.text[:200]}")
                    if attempt < max_attempts:
                        time.sleep(1.0)
                        url = FALLBACK_SEARCH_URL  # try fallback URL on retry
                        continue
                    record_failure(self.name)
                    return None

                # Other 4xx
                logger.warning(f"[Foursquare] Unexpected HTTP {resp.status_code}: {resp.text[:200]}")
                record_failure(self.name)
                return None

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                logger.warning(f"[Foursquare] {type(exc).__name__} on attempt {attempt}: {exc}")
                if attempt < max_attempts:
                    time.sleep(1.0)
                    url = FALLBACK_SEARCH_URL
                    continue
                record_failure(self.name)
                return None
            except Exception as exc:
                logger.error(f"[Foursquare] Request exception: {exc}")
                record_failure(self.name)
                return None

        return None

    def _parse_results(self, data: dict, kind: KindType) -> list[dict]:
        """Normalize raw Foursquare items into uniform schema."""
        raw_items = data.get("results", [])
        places: list[dict] = []

        for item in raw_items:
            name = (item.get("name") or "").strip()
            if not name:
                continue

            # Coordinates: geocodes.main.latitude / longitude
            geocodes = item.get("geocodes", {})
            main_geo = geocodes.get("main", {}) if isinstance(geocodes, dict) else {}
            lat = main_geo.get("latitude")
            lon = main_geo.get("longitude")

            if lat is None or lon is None:
                # Fallback to location coords if present
                loc = item.get("location", {})
                lat = loc.get("latitude")
                lon = loc.get("longitude")

            if lat is None or lon is None:
                continue

            # Category
            cats = item.get("categories", [])
            cat_name = cats[0].get("name", kind.capitalize()) if cats else kind.capitalize()

            # Location / Address
            loc = item.get("location", {})
            address = loc.get("formatted_address") or loc.get("address") or ""

            # Rating: Foursquare provides float rating (0.0 to 10.0)
            raw_rating = item.get("rating")
            rating = float(raw_rating) if raw_rating is not None else None
            star_rating = round(min(5.0, max(1.0, rating / 2.0)), 1) if rating is not None else 4.0

            # Price level: int 1..4
            price_level = item.get("price")
            if price_level is not None:
                try:
                    price_level = int(price_level)
                except (ValueError, TypeError):
                    price_level = None

            website = item.get("website")
            phone = item.get("tel")

            place = {
                "name": name,
                "category": cat_name,
                "lat": float(lat),
                "lon": float(lon),
                "address": address,
                "rating": rating,
                "star_rating": star_rating,
                "price_level": price_level,
                "website": website,
                "phone": phone,
                "source": "foursquare",
                "tags": {},
            }
            places.append(place)

        return places

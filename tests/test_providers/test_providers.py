"""
Tests for Step 3: Places Provider Layer (Foursquare, Circuit Breakers, Overpass, Negative Caching, Fallbacks).

Requirements tested:
1. Foursquare provider success (attractions, restaurants, hotels with estimated pricing)
2. Foursquare HTTP error handling: 401, 429, 500 (with retry), timeout (with retry)
3. Foursquare daily call limit counter (skips when limit reached)
4. Missing API key (provider skipped)
5. Circuit breaker: trips after 3 failures, stays open for 5m, closes on reset/success
6. Overpass circuit breaker: trips when all mirrors fail; second plan returns in < 1 second
7. Negative caching: empty results cached for 10 minutes, avoiding repeated slow calls
8. Complete agent fallback: when all external providers fail, agents still return complete data
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

import app.db.database as db
from app.agents.attraction_agent import get_attractions_for_trip
from app.agents.hotel_agent import get_hotels
from app.agents.restaurant_agent import get_restaurants_for_trip
from app.providers.circuit_breaker import (
    is_circuit_open,
    record_failure,
    record_success,
    reset_circuit,
    trip_circuit,
)
from app.providers.foursquare import (
    FoursquarePlacesProvider,
    get_daily_calls,
    increment_daily_calls,
    is_daily_limit_reached,
    reset_daily_calls,
)
from app.providers.registry import estimate_hotel_pricing, search_places
from app.tools.cache import _FALLBACK, cache_clear, cache_get, cache_set
from app.tools.places_tools import _fetch_overpass_with_retry, get_attractions, get_restaurants


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_environment(tmp_path, monkeypatch):
    """Use an isolated temp DB and clean fallback cache for each test."""
    db_file = tmp_path / "test_providers.db"
    monkeypatch.setenv("DATABASE_URL", str(db_file))
    db._INITIALIZED_PATHS.clear()
    _FALLBACK.clear()
    db.init_db()

    # Reset circuit breakers & daily budgets
    reset_circuit("foursquare")
    reset_circuit("overpass")
    reset_daily_calls()

    yield str(db_file)

    _FALLBACK.clear()
    reset_circuit("foursquare")
    reset_circuit("overpass")


MOCK_FSQ_RESPONSE = {
    "results": [
        {
            "fsq_id": "fsq_123",
            "name": "Grand Palace Bangkok",
            "categories": [{"name": "Historic Site"}],
            "geocodes": {
                "main": {
                    "latitude": 13.7500,
                    "longitude": 100.4915,
                }
            },
            "location": {
                "address": "Na Phra Lan Rd",
                "formatted_address": "Na Phra Lan Rd, Bangkok 10200",
            },
            "rating": 9.2,
            "price": 3,
            "website": "https://www.royalgrandpalace.th",
            "tel": "+66 2 623 5500",
        }
    ]
}

MOCK_FSQ_HOTEL_RESPONSE = {
    "results": [
        {
            "fsq_id": "fsq_hotel_456",
            "name": "The Peninsula Bangkok",
            "categories": [{"name": "Hotel"}],
            "geocodes": {
                "main": {
                    "latitude": 13.7250,
                    "longitude": 100.5100,
                }
            },
            "location": {
                "address": "333 Charoen Nakhon Rd",
                "formatted_address": "333 Charoen Nakhon Rd, Bangkok",
            },
            "rating": 9.4,
            "price": 4,
            "website": "https://www.peninsula.com/bangkok",
            "tel": "+66 2 020 2888",
        }
    ]
}


# ── 1. Foursquare Provider Success ────────────────────────────────────────────

def test_foursquare_provider_success(monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test_key_abc")
    provider = FoursquarePlacesProvider()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_FSQ_RESPONSE

    with patch("requests.get", return_value=mock_resp) as mock_get:
        results = provider.search(
            kind="attractions",
            lat=13.7500,
            lon=100.4915,
            radius_m=3000,
            limit=5,
        )

    assert len(results) == 1
    place = results[0]
    assert place["name"] == "Grand Palace Bangkok"
    assert place["category"] == "Historic Site"
    assert place["lat"] == 13.7500
    assert place["lon"] == 100.4915
    assert place["rating"] == 9.2
    assert place["star_rating"] == 4.6
    assert place["price_level"] == 3
    assert place["website"] == "https://www.royalgrandpalace.th"
    assert place["source"] == "foursquare"

    # Verify headers sent
    call_kwargs = mock_get.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer test_key_abc"
    assert call_kwargs["headers"]["X-Places-Api-Version"] == "2025-06-17"


def test_foursquare_hotel_pricing_estimates():
    raw_hotel = MOCK_FSQ_HOTEL_RESPONSE["results"][0]
    provider = FoursquarePlacesProvider()
    parsed = provider._parse_results(MOCK_FSQ_HOTEL_RESPONSE, "hotels")[0]

    estimated = estimate_hotel_pricing(parsed, budget_total=2000.0, travelers=2)
    assert estimated["name"] == "The Peninsula Bangkok"
    assert estimated["price_source"] == "estimated"
    assert estimated["price_per_night_usd"] > 0
    assert estimated["star_rating"] == 4.7
    assert estimated["location_lat"] == 13.7250
    assert estimated["location_lon"] == 100.5100
    assert "Swimming Pool" in estimated["amenities"]


# ── 2. Missing Key & HTTP Errors (401, 429, 500, Timeout) ─────────────────────

def test_foursquare_missing_key(monkeypatch):
    monkeypatch.delenv("FOURSQUARE_API_KEY", raising=False)
    provider = FoursquarePlacesProvider(api_key="")
    assert not provider.is_configured()

    with patch("requests.get") as mock_get:
        results = provider.search("attractions", 13.75, 100.5, 3000, 5)
        assert results == []
        mock_get.assert_not_called()


def test_foursquare_401_unauthorized(monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "invalid_key")
    provider = FoursquarePlacesProvider()

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = '{"message": "Unauthorized"}'

    with patch("requests.get", return_value=mock_resp):
        results = provider.search("attractions", 13.75, 100.5, 3000, 5)
        assert results == []


def test_foursquare_429_rate_limited(monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test_key")
    provider = FoursquarePlacesProvider()

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = '{"message": "Rate limit exceeded"}'

    with patch("requests.get", return_value=mock_resp):
        results = provider.search("restaurants", 13.75, 100.5, 3000, 5)
        assert results == []


def test_foursquare_500_retries_once(monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test_key")
    provider = FoursquarePlacesProvider()

    mock_fail = MagicMock()
    mock_fail.status_code = 500
    mock_fail.text = "Internal Server Error"

    mock_ok = MagicMock()
    mock_ok.status_code = 200
    mock_ok.json.return_value = MOCK_FSQ_RESPONSE

    # Fails first, succeeds on second attempt
    with patch("requests.get", side_effect=[mock_fail, mock_ok]) as mock_get, \
         patch("time.sleep"):
        results = provider.search("attractions", 13.75, 100.5, 3000, 5)
        assert len(results) == 1
        assert mock_get.call_count == 2


def test_foursquare_timeout_retries_and_fails(monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test_key")
    provider = FoursquarePlacesProvider()

    # Times out on both attempts
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Read timeout")) as mock_get, \
         patch("time.sleep"):
        results = provider.search("attractions", 13.75, 100.5, 3000, 5)
        assert results == []
        assert mock_get.call_count == 2


# ── 3. Daily Call Limit Counter ───────────────────────────────────────────────

def test_foursquare_daily_limit_reached(monkeypatch):
    monkeypatch.setenv("FOURSQUARE_API_KEY", "test_key")
    monkeypatch.setenv("FOURSQUARE_DAILY_LIMIT", "5")
    provider = FoursquarePlacesProvider()

    # Simulate 5 calls made today
    for _ in range(5):
        increment_daily_calls()

    assert get_daily_calls() == 5
    assert is_daily_limit_reached()

    with patch("requests.get") as mock_get:
        results = provider.search("attractions", 13.75, 100.5, 3000, 5)
        assert results == []
        mock_get.assert_not_called()


# ── 4. Circuit Breaker Opening & Closing ──────────────────────────────────────

def test_circuit_breaker_opening_and_closing():
    name = "test_provider"
    reset_circuit(name)
    assert not is_circuit_open(name)

    # 1st failure
    assert not record_failure(name)
    assert not is_circuit_open(name)

    # 2nd failure
    assert not record_failure(name)
    assert not is_circuit_open(name)

    # 3rd consecutive failure -> trips breaker
    tripped = record_failure(name)
    assert tripped is True
    assert is_circuit_open(name)

    # Success closes the breaker
    record_success(name)
    assert not is_circuit_open(name)


def test_circuit_breaker_cooldown_expiry():
    name = "cooldown_test"
    trip_circuit(name, cooldown_s=300)
    assert is_circuit_open(name)

    # Simulate time advancing 301 seconds into the future
    with patch("time.time", return_value=time.time() + 305):
        assert not is_circuit_open(name)


# ── 5. Overpass Circuit Breaker & Fast Second Call (< 1s) ─────────────────────

def test_overpass_circuit_breaker_and_fast_second_call():
    """
    When Overpass fails, it trips the circuit breaker for 5 minutes.
    A subsequent call must return in under 1 second without waiting for slow mirrors.
    """
    reset_circuit("overpass")

    # Mock all Overpass mirrors failing slowly (e.g. 1.0s timeout per mirror)
    def slow_post_fail(url, data, headers, timeout):
        time.sleep(0.05)
        return None

    with patch("requests.post", side_effect=slow_post_fail):
        res1 = _fetch_overpass_with_retry("test_query", timeout=1)
        assert res1 is None

    # Circuit breaker must now be OPEN for 'overpass'
    assert is_circuit_open("overpass")

    # Second call should short-circuit immediately without making any requests
    t0 = time.time()
    with patch("requests.post") as mock_post:
        res2 = _fetch_overpass_with_retry("test_query", timeout=16)
        elapsed = time.time() - t0
        assert res2 is None
        mock_post.assert_not_called()

    assert elapsed < 1.0, f"Second call took {elapsed:.3f}s, expected < 1s!"


# ── 6. Negative Caching (Empty Results Cached for 10m) ────────────────────────

def test_negative_caching_attractions_and_restaurants():
    """Empty results for a location are negatively cached for 10 minutes."""
    cache_clear()
    lat, lon = 12.3456, 78.9012

    # Mock Overpass returning empty elements
    with patch("app.tools.places_tools._fetch_overpass_with_retry", return_value={"elements": []}):
        res1 = get_attractions(lat, lon, radius_m=5000, limit=10)
        assert res1 == []

    # Second call should hit the negative cache directly
    with patch("app.tools.places_tools._fetch_overpass_with_retry") as mock_fetch:
        res2 = get_attractions(lat, lon, radius_m=5000, limit=10)
        assert res2 == []
        mock_fetch.assert_not_called()


# ── 7. Fallback Chain: Complete Data When Every External Provider Fails ───────

@pytest.mark.asyncio
async def test_agents_return_complete_data_when_all_providers_fail(monkeypatch):
    """
    When Foursquare, Overpass, and Nominatim all fail / return empty,
    attraction_agent, restaurant_agent, and hotel_agent must still return complete data
    via their respective AI and mock fallbacks without crashing.
    """
    monkeypatch.delenv("FOURSQUARE_API_KEY", raising=False)
    trip_circuit("overpass", cooldown_s=300)

    # Mock Nominatim returning empty
    with patch("app.providers.registry.search_places_nearby", return_value=[]), \
         patch("app.tools.geocode_tools.geocode_place", return_value={"lat": 13.75, "lon": 100.5}):

        # 1. Hotel Agent (uses mock dataset / AI fallback)
        hotel_state = {"destination": "Jaipur", "budget_total": 1500, "errors": []}
        h_res = await get_hotels(hotel_state)
        assert len(h_res["hotels"]) > 0
        first_h = h_res["hotels"][0]
        assert "name" in first_h
        assert "price_per_night_usd" in first_h
        assert first_h.get("price_source") == "estimated"

        # 2. Attraction Agent (uses AI place fallback)
        fake_ai_places = [
            {"name": "Wat Pho", "category": "Temple", "lat": 13.7466, "lon": 100.4933, "match_reason": "Iconic"}
        ]
        with patch("app.agents.attraction_agent._ai_place_fallback", return_value=fake_ai_places):
            attr_state = {"destination": "Bangkok", "preferences": ["temples"], "errors": []}
            a_res = await get_attractions_for_trip(attr_state)
            assert len(a_res["attractions"]) > 0
            assert a_res["attractions"][0]["name"] == "Wat Pho"

        # 3. Restaurant Agent (uses AI place fallback)
        fake_ai_restaurants = [
            {"name": "Thip Samai Pad Thai", "category": "Thai", "lat": 13.7527, "lon": 100.5047, "match_reason": "Legendary"}
        ]
        with patch("app.agents.restaurant_agent._ai_place_fallback", return_value=fake_ai_restaurants):
            rest_state = {"destination": "Bangkok", "preferences": ["thai"], "errors": []}
            r_res = await get_restaurants_for_trip(rest_state)
            assert len(r_res["restaurants"]) > 0
            assert r_res["restaurants"][0]["name"] == "Thip Samai Pad Thai"

"""
Global test configuration, fixtures, and network blocking for pytest.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Optional

import pytest
import requests

import app.db.database as db
from app.tools.cache import _FALLBACK, cache_clear

# ── 1. Network Blocking ────────────────────────────────────────────────────────

_ORIGINAL_SOCKET_CONNECT = socket.socket.connect


def _blocked_socket_connect(self, address):
    host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
    # Allow local connections (e.g. TestClient, FastAPI in-process, localhost)
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return _ORIGINAL_SOCKET_CONNECT(self, address)
    raise RuntimeError(
        f"Real network access to '{address}' is blocked in tests! "
        f"Use mocks (fake_http) or mark test with @pytest.mark.network."
    )


@pytest.fixture(autouse=True)
def block_external_network(request, monkeypatch):
    """
    Blocks outgoing external network calls for all tests unless decorated with @pytest.mark.network.
    Localhost and in-memory ASGI client calls remain permitted.
    """
    if "network" in request.keywords:
        yield
        return

    monkeypatch.setattr(socket.socket, "connect", _blocked_socket_connect)
    yield


# ── 2. Isolated Temp SQLite Database ──────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch) -> str:
    """Provide an isolated temporary SQLite database path for the test."""
    db_file = tmp_path / "test_travel.db"
    monkeypatch.setenv("DATABASE_URL", str(db_file))
    db._INITIALIZED_PATHS.clear()
    _FALLBACK.clear()
    cache_clear()
    db.init_db()
    yield str(db_file)
    _FALLBACK.clear()
    cache_clear()


# ── 3. Fake LLM Fixture ────────────────────────────────────────────────────────

class FakeLLM:
    """
    Configurable canned LLM response generator that monkeypatches
    app.llm.factory._call_groq and app.llm.factory._call_openrouter.
    """

    def __init__(self):
        self.down: bool = False
        self.call_history: list[dict] = []

    def set_down(self, down: bool = True):
        self.down = down

    def respond(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        self.call_history.append({"prompt": prompt, "system": system_instruction})
        if self.down:
            raise RuntimeError("FakeLLM: Service unavailable (LLM is down).")

        p_lower = prompt.lower()

        # Day writing prompt (Summary Agent)
        if "day type:" in p_lower or "travel itinerary writer" in p_lower or "write day" in p_lower:
            return json.dumps({
                "morning": "Start with a guided exploration of iconic historic monuments and sacred temple grounds.",
                "afternoon": "Enjoy traditional noodles and fresh local specialties at a celebrated neighbourhood bistro.",
                "evening": "Stroll through the bustling night bazaars, riverside promenades, and scenic viewpoints.",
                "notes": "Warm conditions; stay hydrated, dress modestly for temples, and wear walking shoes.",
            })

        # Overview / Catchy Title prompt
        if "catchy trip title" in p_lower or "trip_title" in p_lower:
            return json.dumps({
                "trip_title": "Grand Cultural Journey",
                "overview_paragraph": (
                    "An unforgettable discovery featuring majestic temples, world-class street gastronomy, "
                    "and dynamic cultural highlights."
                ),
            })

        # Hotels prompt
        if "hotel" in p_lower:
            return json.dumps([
                {
                    "name": "Grand Riverside Heritage Hotel",
                    "rating": 4.6,
                    "star_rating": 4.5,
                    "price_per_night": 125.0,
                    "address": "100 Riverside Promenade",
                    "amenities": ["Free WiFi", "Swimming Pool", "Breakfast Included"],
                    "source": "ai",
                },
                {
                    "name": "Old Town Boutique Suites",
                    "rating": 4.3,
                    "star_rating": 4.0,
                    "price_per_night": 88.0,
                    "address": "45 Heritage Way",
                    "amenities": ["Free WiFi", "Air Conditioning", "Terrace"],
                    "source": "ai",
                },
            ])

        # Packing checklist prompt
        if "packing" in p_lower or "checklist" in p_lower:
            return json.dumps([
                "Valid passport, visas and travel documentation",
                "Comfortable broken-in walking shoes",
                "Breathable lightweight cotton clothing",
                "Universal travel plug adapter and power bank",
                "Reusable water bottle and hydration pack",
                "UV-blocking sunglasses and high-SPF sunscreen",
                "Compact umbrella or light rain shell",
            ])

        # Budget breakdown prompt
        if "budget" in p_lower:
            return json.dumps({
                "accommodation": 500.0,
                "food": 400.0,
                "activities": 300.0,
                "transport": 200.0,
                "contingency": 100.0,
            })

        # Transport guide prompt
        if "transport" in p_lower:
            return json.dumps({
                "arrival": "Take the airport rail link or metered express taxi directly into downtown.",
                "local_transport": "The rapid transit skytrain/subway and walkable central streets are easiest.",
                "tips": "Purchase a rechargeable smart transit pass to skip ticket vending queues.",
            })

        # Places / Attractions / Restaurants / Landmarks fallback
        if (
            "place" in p_lower
            or "attraction" in p_lower
            or "restaurant" in p_lower
            or "famous" in p_lower
            or "landmark" in p_lower
        ):
            return json.dumps([
                {
                    "name": "Wat Pho Grand Sanctuary",
                    "category": "Historic Temple",
                    "description": "Famed reclining golden sanctuary and historic monastery.",
                    "lat": 13.7465,
                    "lon": 100.4933,
                    "tags": {"tourism": "attraction"},
                },
                {
                    "name": "Grand Palace Cultural Grounds",
                    "category": "Royal Palace",
                    "description": "Historic residence of kings with ornate traditional architecture.",
                    "lat": 13.7515,
                    "lon": 100.4927,
                    "tags": {"tourism": "attraction"},
                },
                {
                    "name": "Thip Samai Heritage Noodle House",
                    "category": "Thai Restaurant",
                    "description": "Legendary spot renowned for award-winning pad thai dishes.",
                    "lat": 13.7520,
                    "lon": 100.5000,
                    "tags": {"amenity": "restaurant", "cuisine": "thai"},
                },
                {
                    "name": "Chinatown Night Market Eateries",
                    "category": "Street Food Market",
                    "description": "Vibrant night dining area featuring authentic culinary classics.",
                    "lat": 13.7540,
                    "lon": 100.5020,
                    "tags": {"amenity": "restaurant"},
                },
            ])

        # Destination suggestions prompt
        if "destination" in p_lower or "suggest" in p_lower:
            return json.dumps([
                {
                    "destination": "Bangkok, Thailand",
                    "reason": "Rich heritage architecture, historic temples, and legendary culinary culture.",
                    "best_months": "Nov-Feb",
                    "estimated_budget_usd": 1500,
                },
                {
                    "destination": "Tokyo, Japan",
                    "reason": "Harmonious blend of ultramodern landmarks, historic shrines, and food culture.",
                    "best_months": "Mar-May",
                    "estimated_budget_usd": 2500,
                },
            ])

        return json.dumps({"status": "ok", "message": "Canned response"})


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    """Fixture that mocks Groq and OpenRouter LLM calls with deterministic canned responses."""
    fl = FakeLLM()
    monkeypatch.setattr("app.llm.factory._call_groq", fl.respond)
    monkeypatch.setattr("app.llm.factory._call_openrouter", fl.respond)
    return fl


# ── 4. Fake HTTP Fixture ───────────────────────────────────────────────────────

class FakeHTTP:
    """
    Configurable deterministic HTTP response generator for external APIs
    (Nominatim, Open-Meteo, Frankfurter, Overpass).
    """

    def __init__(self):
        self.overpass_down: bool = False
        self.overpass_mode: str = "success"  # "success", "500", "504", "timeout"
        self.all_apis_down: bool = False
        self.call_history: list[dict] = []

    def set_overpass_down(self, mode: str = "504"):
        self.overpass_down = True
        self.overpass_mode = mode

    def set_all_apis_down(self, down: bool = True):
        self.all_apis_down = down

    def _mock_response(self, status_code: int, data: Any) -> requests.Response:
        resp = requests.Response()
        resp.status_code = status_code
        if isinstance(data, (dict, list)):
            resp._content = json.dumps(data).encode("utf-8")
            resp.headers["Content-Type"] = "application/json"
        elif isinstance(data, str):
            resp._content = data.encode("utf-8")
        else:
            resp._content = b""
        return resp

    def get(self, url: str, *args, **kwargs) -> requests.Response:
        self.call_history.append({"method": "GET", "url": url, "kwargs": kwargs})

        if self.all_apis_down:
            raise requests.exceptions.ConnectionError(f"FakeHTTP: External API down ({url})")

        # Nominatim Geocoding
        if "nominatim.openstreetmap.org/search" in url:
            params = kwargs.get("params") or {}
            q = (params.get("q") or "").strip().lower()
            if "xyz_non_existent" in q:
                return self._mock_response(200, [])
            # Return coordinates for Bangkok or requested place
            return self._mock_response(200, [
                {
                    "lat": "13.7563",
                    "lon": "100.5018",
                    "display_name": "Bangkok, Phra Nakhon, Thailand",
                    "address": {"country": "Thailand"},
                    "boundingbox": ["13.5", "14.0", "100.3", "100.7"],
                }
            ])

        # Open-Meteo Weather
        if "open-meteo.com" in url:
            return self._mock_response(200, {
                "daily": {
                    "time": ["2026-11-10", "2026-11-11", "2026-11-12"],
                    "temperature_2m_max": [31.5, 32.0, 31.0],
                    "temperature_2m_min": [24.0, 24.5, 23.8],
                    "precipitation_sum": [0.0, 1.5, 0.0],
                    "weathercode": [1, 61, 2],
                }
            })

        # Frankfurter Exchange Rates
        if "frankfurter.app" in url:
            return self._mock_response(200, {
                "amount": 100.0,
                "base": "USD",
                "date": "2026-11-10",
                "rates": {
                    "INR": 83.5,
                    "EUR": 0.92,
                    "THB": 35.5,
                    "GBP": 0.79,
                    "JPY": 155.0,
                    "USD": 1.0,
                },
            })

        # Foursquare Places API
        if "foursquare.com" in url:
            return self._mock_response(200, {"results": []})

        return self._mock_response(200, {})

    def post(self, url: str, *args, **kwargs) -> requests.Response:
        self.call_history.append({"method": "POST", "url": url, "kwargs": kwargs})

        if self.all_apis_down:
            raise requests.exceptions.ConnectionError(f"FakeHTTP: External API down ({url})")

        # Overpass API
        if any(host in url for host in ("overpass-api.de", "private.coffee", "kumi.systems")):
            if self.overpass_down:
                if self.overpass_mode == "timeout":
                    raise requests.exceptions.Timeout("FakeHTTP: Overpass timed out")
                code = int(self.overpass_mode) if self.overpass_mode.isdigit() else 504
                return self._mock_response(code, "Overpass server error")

            return self._mock_response(200, {
                "elements": [
                    {
                        "type": "node",
                        "id": 101,
                        "lat": 13.751,
                        "lon": 100.492,
                        "tags": {"name": "Grand Palace Wat Phra Kaew", "tourism": "attraction"},
                    },
                    {
                        "type": "node",
                        "id": 102,
                        "lat": 13.746,
                        "lon": 100.493,
                        "tags": {"name": "Wat Pho Temple Complex", "tourism": "attraction"},
                    },
                    {
                        "type": "node",
                        "id": 201,
                        "lat": 13.752,
                        "lon": 100.502,
                        "tags": {"name": "Thip Samai Pad Thai", "amenity": "restaurant", "cuisine": "thai"},
                    },
                    {
                        "type": "node",
                        "id": 202,
                        "lat": 13.754,
                        "lon": 100.505,
                        "tags": {"name": "Raan Jay Fai Bistro", "amenity": "restaurant", "cuisine": "thai"},
                    },
                ]
            })

        return self._mock_response(200, {})


@pytest.fixture(autouse=True)
def fake_http(request, monkeypatch) -> FakeHTTP:
    """Fixture that intercepts requests.get and requests.post with deterministic canned data."""
    if "network" in request.keywords:
        yield None
        return

    fh = FakeHTTP()
    monkeypatch.setattr(requests, "get", fh.get)
    monkeypatch.setattr(requests, "post", fh.post)
    yield fh

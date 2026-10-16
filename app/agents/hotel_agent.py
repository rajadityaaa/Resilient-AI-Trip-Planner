"""
Hotel Agent: Provides hotel suggestions for trip destination via Provider Registry (Foursquare -> Mock JSON -> LLM).

Hotels from real providers include:
- Real listings: name, location, rating, category
- Prices clearly marked as estimates: price_source: "estimated"
- Deep-links generated via app/tools/booking_links.py
- Mock dataset (mock_hotels.json) kept as fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.agents.state import TripState
from app.llm.factory import SMART_MODEL, clean_json_response, get_llm
from app.llm.prompts.hotel_fallback_prompt import build_hotel_fallback_prompt
from app.providers.registry import search_places
from app.tools.geocode_tools import geocode_place

MOCK_HOTELS_FILE = Path(__file__).parent.parent / "data" / "mock_hotels.json"


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def get_hotels(state: TripState) -> TripState:
    """
    Fetch hotel recommendations for destination.
    Priority order:
    1. Foursquare Places API (real hotel listings with estimated prices and price_source="estimated")
    2. Mock JSON dataset lookup (mock_hotels.json)
    3. LLM generation fallback
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "hotel_agent", "message": "No destination specified."})
        state["hotels"] = []
        return state

    dest_city = dest.split(",")[0].strip().lower()

    # Step 1: Attempt Provider Registry lookup (Foursquare if configured)
    try:
        geo = geocode_place(dest)
        budget = state.get("budget_total", 1000.0)
        provider_hotels, source = search_places(
            kind="hotels",
            lat=geo["lat"],
            lon=geo["lon"],
            radius_m=5000,
            limit=10,
            destination=dest,
            budget_total=budget,
        )
        if provider_hotels and source in ("foursquare", "osm", "nominatim"):
            for h in provider_hotels:
                if "price_source" not in h:
                    h["price_source"] = "estimated"
                if "star_rating" not in h:
                    h["star_rating"] = h.get("rating", 4.0)
                if "price_per_night_usd" not in h:
                    h["price_per_night_usd"] = 85.0
            state["hotels"] = provider_hotels
            return state
    except Exception as err:
        logger_msg = f"Provider search for hotels failed: {err}"
        state["errors"].append({"agent": "hotel_agent", "message": logger_msg})

    # Step 2: Attempt mock JSON dataset lookup (last-resort fallback before AI)
    matched_hotels = []
    if MOCK_HOTELS_FILE.exists():
        try:
            with open(MOCK_HOTELS_FILE, "r", encoding="utf-8") as f:
                dataset = json.load(f)
            for h in dataset:
                city_val = h.get("city", "").lower()
                if dest_city in city_val or city_val in dest_city:
                    item = dict(h)
                    item["source"] = "mock_data"
                    item["price_source"] = "estimated"
                    item["lat"] = item.get("location_lat")
                    item["lon"] = item.get("location_lon")
                    matched_hotels.append(item)
        except Exception as err:
            state["errors"].append({"agent": "hotel_agent", "message": f"Mock dataset load failed: {err}"})

    if matched_hotels:
        state["hotels"] = matched_hotels
        return state

    # Step 3: Fall back to LLM generation if city is not in mock dataset
    try:
        llm = get_llm(model=SMART_MODEL, max_tokens=2000)
        prompt = build_hotel_fallback_prompt(
            destination=dest,
            budget_total=state.get("budget_total", 1000.0),
            budget_currency=state.get("budget_currency", "USD"),
            trip_type=state.get("trip_type", "leisure"),
        )
        resp_text = llm(prompt)

        try:
            generated = clean_json_response(resp_text)
        except json.JSONDecodeError:
            state["errors"].append({
                "agent": "hotel_agent",
                "message": "hotel_agent: LLM response could not be parsed, using estimated hotel tiers",
            })
            state["hotels"] = _placeholder_hotels(state, dest)
            return state

        if not isinstance(generated, list):
            generated = [generated]

        for item in generated:
            item["is_mock"] = True
            item["source"] = "llm_generated"
            item["price_source"] = "estimated"
            if "location_lat" in item and "lat" not in item:
                item["lat"] = item["location_lat"]
            if "location_lon" in item and "lon" not in item:
                item["lon"] = item["location_lon"]

        state["hotels"] = generated
    except Exception as err:
        state["errors"].append({"agent": "hotel_agent", "message": str(err)})
        state["hotels"] = []

    if not state["hotels"]:
        state["hotels"] = _placeholder_hotels(state, dest)
    return state


def _placeholder_hotels(state: TripState, dest: str) -> list:
    """Deterministic fallback hotel list when all suppliers fail."""
    budget = state.get("budget_total", 1000.0)
    per_night = round(budget * 0.35 / 3.0, 2)
    return [
        {
            "name": f"Grand Central Hotel ({dest.title()})",
            "star_rating": 4.5,
            "rating": 9.0,
            "price_level": 3,
            "price_per_night_usd": per_night,
            "price_source": "estimated",
            "location_lat": 0.0,
            "location_lon": 0.0,
            "lat": 0.0,
            "lon": 0.0,
            "amenities": ["Free WiFi", "Breakfast", "Gym"],
            "source": "fallback",
        },
        {
            "name": f"Comfort Suites & Inn ({dest.title()})",
            "star_rating": 3.5,
            "rating": 7.5,
            "price_level": 2,
            "price_per_night_usd": round(per_night * 0.65, 2),
            "price_source": "estimated",
            "location_lat": 0.0,
            "location_lon": 0.0,
            "lat": 0.0,
            "lon": 0.0,
            "amenities": ["Free WiFi", "AC"],
            "source": "fallback",
        },
    ]

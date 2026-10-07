"""
Hotel Agent: Provides hotel suggestions for trip destination.
MVP uses mock data from app/data/mock_hotels.json with LLM fallback generation.

API REPLACEMENT SEAM:
To wire a live hotel supplier API (e.g. Booking.com affiliate API, Amadeus Self-Service API free tier),
replace the body of this function to call your API endpoint. Maintain the exact same async signature:
  async def get_hotels(state: TripState) -> TripState
and populate state["hotels"] with a list of dictionaries. Zero changes needed elsewhere in the codebase.
"""
import json
from pathlib import Path
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response, SMART_MODEL
from app.llm.prompts.hotel_fallback_prompt import build_hotel_fallback_prompt

MOCK_HOTELS_FILE = Path(__file__).parent.parent / "data" / "mock_hotels.json"


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def get_hotels(state: TripState) -> TripState:
    """
    Fetch hotel recommendations for destination.
    Uses mock dataset if city matches, otherwise generates mock inventory via LLM.
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

    # Step 1: Attempt mock JSON dataset lookup
    matched_hotels = []
    if MOCK_HOTELS_FILE.exists():
        try:
            with open(MOCK_HOTELS_FILE, "r", encoding="utf-8") as f:
                dataset = json.load(f)
            for h in dataset:
                city_val = h.get("city", "").lower()
                if dest_city in city_val or city_val in dest_city:
                    matched_hotels.append(h)
        except Exception as err:
            state["errors"].append({"agent": "hotel_agent", "message": f"Mock dataset load failed: {err}"})

    if matched_hotels:
        state["hotels"] = matched_hotels
        return state

    # Step 2: Fall back to LLM generation if city is not in mock dataset
    try:
        llm = get_llm(model=SMART_MODEL, max_tokens=2000)
        prompt = build_hotel_fallback_prompt(
            destination=dest,
            budget_total=state.get("budget_total", 1000.0),
            budget_currency=state.get("budget_currency", "USD"),
            trip_type=state.get("trip_type", "leisure")
        )
        resp_text = llm(prompt)
        
        try:
            generated = clean_json_response(resp_text)
        except json.JSONDecodeError:
            state["errors"].append({
                "agent": "hotel_agent",
                "message": "hotel_agent: LLM response could not be parsed, using estimated hotel tiers"
            })
            state["hotels"] = _placeholder_hotels(state, dest)
            return state

        if not isinstance(generated, list):
            generated = [generated]

        for item in generated:
            item["is_mock"] = True
            item["source"] = "llm_generated"

        state["hotels"] = generated
    except Exception as err:
        state["errors"].append({"agent": "hotel_agent", "message": str(err)})
        state["hotels"] = []

    if not state["hotels"]:
        state["hotels"] = _placeholder_hotels(state, dest)
    return state


def _placeholder_hotels(state: TripState, dest: str) -> list:
    """Last resort so the section is never empty: price tiers derived from the user's budget."""
    city = dest.split(",")[0].strip()
    try:
        from datetime import datetime
        nights = max(1, (datetime.strptime(state["end_date"], "%Y-%m-%d") - datetime.strptime(state["start_date"], "%Y-%m-%d")).days)
    except Exception:
        nights = 4
    per_night = max(20.0, float(state.get("budget_total", 1000.0)) * 0.40 / nights / max(1, -(-int(state.get("travelers", 1)) // 2)))
    tiers = [("Budget stays", 0.6, 3.5), ("Mid-range hotels", 1.0, 4.0), ("Upscale hotels", 1.7, 4.5)]
    return [{
        "name": f"{label} in {city}", "city": city, "star_rating": stars,
        "price_per_night_usd": round(per_night * mult, 2), "amenities": ["Check live availability on Booking.com"],
        "is_mock": True, "source": "estimated_tier",
    } for label, mult, stars in tiers]

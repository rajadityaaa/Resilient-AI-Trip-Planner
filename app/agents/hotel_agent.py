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
from app.llm.factory import get_llm, clean_json_response
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
        llm = get_llm()
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
            # Retry once with stricter formatting instructions
            retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
            resp_text = llm(prompt + retry_instruction)
            try:
                generated = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Log a non-technical error and use fallback hotel list
                state["errors"].append({
                    "agent": "hotel_agent",
                    "message": "hotel_agent: LLM response could not be parsed after retry, using fallback hotel data"
                })
                state["hotels"] = []
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

    return state

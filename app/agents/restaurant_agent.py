"""
Restaurant Agent: Fetches dining options via Overpass and flags best matches using LLM.
"""
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.restaurant_ranking_prompt import build_restaurant_ranking_prompt
from app.tools.geocode_tools import geocode_place
from app.tools.places_tools import get_restaurants


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def get_restaurants_for_trip(state: TripState) -> TripState:
    """
    Fetch restaurants near destination, pass detected cuisine filter, and rank using LLM.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "restaurant_agent", "message": "No destination available."})
        state["restaurants"] = []
        return state

    try:
        geo = geocode_place(dest)

        # Detect cuisine keywords from user preferences
        prefs = state.get("preferences", [])
        cuisine_kw = None
        for p in prefs:
            p_lower = p.lower()
            if any(k in p_lower for k in ["italian", "indian", "chinese", "japanese", "mexican", "thai", "vegetarian", "vegan", "seafood", "street food"]):
                cuisine_kw = p
                break

        raw_restaurants = get_restaurants(geo["lat"], geo["lon"], radius_m=3000, cuisine=cuisine_kw, limit=20)
        if not raw_restaurants and cuisine_kw:
            # Fall back without cuisine filter if strict filter returned 0
            raw_restaurants = get_restaurants(geo["lat"], geo["lon"], radius_m=3000, cuisine=None, limit=20)

        if not raw_restaurants:
            state["restaurants"] = []
            return state

        # Use LLM to rank and match restaurants
        try:
            llm = get_llm()
            prompt = build_restaurant_ranking_prompt(prefs, raw_restaurants)
            resp_text = llm(prompt)
            
            try:
                ranked = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Retry once with stricter formatting instructions
                retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
                resp_text = llm(prompt + retry_instruction)
                try:
                    ranked = clean_json_response(resp_text)
                except json.JSONDecodeError:
                    # Log a non-technical error and fall back to raw list slice
                    state["errors"].append({
                        "agent": "restaurant_agent",
                        "message": "restaurant_agent: LLM response could not be parsed after retry, using raw restaurants"
                    })
                    state["restaurants"] = raw_restaurants[:10]
                    return state

            if isinstance(ranked, list) and len(ranked) > 0:
                # Deduplicate by name (LLM may repeat entries)
                seen = set()
                deduped = []
                for r in ranked:
                    rname = (r.get("name") or "").strip().lower()
                    if rname and rname not in seen:
                        seen.add(rname)
                        deduped.append(r)
                state["restaurants"] = deduped[:10]
            else:
                state["restaurants"] = raw_restaurants[:10]
        except Exception:
            state["restaurants"] = raw_restaurants[:10]

    except Exception as err:
        state["errors"].append({"agent": "restaurant_agent", "message": str(err)})
        state["restaurants"] = []

    return state

"""
Attraction Agent: Fetches points of interest via Overpass and ranks them using LLM against user preferences.
"""
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.attraction_ranking_prompt import build_attraction_ranking_prompt
from app.tools.geocode_tools import geocode_place
from app.tools.places_tools import get_attractions


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def get_attractions_for_trip(state: TripState) -> TripState:
    """
    Fetch attractions near destination and rank them using LLM.
    Capped at top 10 items.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "attraction_agent", "message": "No destination available."})
        state["attractions"] = []
        return state

    try:
        geo = geocode_place(dest)
        raw_attractions = get_attractions(geo["lat"], geo["lon"], radius_m=5000, limit=20)

        if not raw_attractions:
            state["attractions"] = []
            return state

        # Use LLM to rank and filter raw attractions according to user preferences
        try:
            llm = get_llm()
            prompt = build_attraction_ranking_prompt(state.get("preferences", []), raw_attractions)
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
                        "agent": "attraction_agent",
                        "message": "attraction_agent: LLM response could not be parsed after retry, using raw attractions"
                    })
                    state["attractions"] = raw_attractions[:10]
                    return state

            if isinstance(ranked, list) and len(ranked) > 0:
                # Deduplicate by name (LLM may repeat entries)
                seen = set()
                deduped = []
                for a in ranked:
                    aname = (a.get("name") or "").strip().lower()
                    if aname and aname not in seen:
                        seen.add(aname)
                        deduped.append(a)
                state["attractions"] = deduped[:10]
            else:
                state["attractions"] = raw_attractions[:10]
        except Exception:
            # Fall back to raw list slice if LLM fails
            state["attractions"] = raw_attractions[:10]

    except Exception as err:
        state["errors"].append({"agent": "attraction_agent", "message": str(err)})
        state["attractions"] = []

    return state

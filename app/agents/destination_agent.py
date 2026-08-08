"""
Destination Agent: Suggests candidate destinations when state["destination"] is None.
"""
import json
from typing import Optional
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.destination_prompt import build_destination_prompt
from app.tools.geocode_tools import geocode_place, GeocodeNotFoundError


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def suggest_destinations(state: TripState) -> TripState:
    """
    Suggest candidate destinations if user hasn't specified one.
    Validates each candidate via geocode_place(). Discards ungeocodeable entries.
    """
    _init_errors(state)

    dest = state.get("destination")
    if dest and isinstance(dest, str) and dest.strip():
        # Destination already supplied by user; skip suggestion
        return state

    try:
        llm = get_llm()
        prompt = build_destination_prompt(
            trip_type=state.get("trip_type", "leisure"),
            preferences=state.get("preferences", []),
            origin=state.get("origin", "New Delhi"),
            budget_total=state.get("budget_total", 1000.0),
            budget_currency=state.get("budget_currency", "USD")
        )

        response_text = llm(prompt)
        
        try:
            parsed = clean_json_response(response_text)
        except json.JSONDecodeError:
            # Retry once with stricter formatting instructions
            retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
            response_text = llm(prompt + retry_instruction)
            try:
                parsed = clean_json_response(response_text)
            except json.JSONDecodeError:
                # Log a non-technical error and use empty suggestions list
                state["errors"].append({
                    "agent": "destination_agent",
                    "message": "destination_agent: LLM response could not be parsed after retry, no suggestions available"
                })
                state["destination_suggestions"] = []
                return state

        if not isinstance(parsed, list):
            parsed = [parsed]

        validated_suggestions = []
        for cand in parsed:
            dest_name = cand.get("destination")
            if not dest_name:
                continue

            try:
                geo = geocode_place(dest_name)
                cand["lat"] = geo["lat"]
                cand["lon"] = geo["lon"]
                cand["country"] = geo["country"]
                validated_suggestions.append(cand)
            except Exception:
                # Discard candidate if geocoding fails
                continue

        state["destination_suggestions"] = validated_suggestions
    except Exception as err:
        state["errors"].append({"agent": "destination_agent", "message": str(err)})
        state["destination_suggestions"] = []

    return state

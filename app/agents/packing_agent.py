"""
Packing Agent: Generates tailored packing checklist from destination weather & trip type.
"""
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.packing_prompt import build_packing_prompt


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def build_packing_list(state: TripState) -> TripState:
    """
    Generate customized packing checklist.
    """
    _init_errors(state)

    weather_info = state.get("weather", {})
    weather_summary = "Moderate climate"
    if weather_info and isinstance(weather_info, dict):
        daily = weather_info.get("daily", [])
        if daily and len(daily) > 0:
            conds = [d.get("condition", "") for d in daily[:3]]
            temps = [f"{d.get('temp_min', 0):.0f}-{d.get('temp_max', 0):.0f}°C" for d in daily[:3]]
            weather_summary = f"Conditions: {', '.join(conds)}. Temps: {', '.join(temps)}"

    try:
        llm = get_llm()
        prompt = build_packing_prompt(
            weather_summary=weather_summary,
            trip_type=state.get("trip_type", "leisure"),
            preferences=state.get("preferences", [])
        )
        resp_text = llm(prompt)
        
        try:
            items = clean_json_response(resp_text)
        except json.JSONDecodeError:
            # Retry once with stricter formatting instructions
            retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
            resp_text = llm(prompt + retry_instruction)
            try:
                items = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Log a non-technical error and use fallback packing list
                state["errors"].append({
                    "agent": "packing_agent",
                    "message": "packing_agent: LLM response could not be parsed after retry, using fallback packing list"
                })
                state["packing_list"] = [
                    "Comfortable walking shoes",
                    "Weather-appropriate clothing layers",
                    "Passport and travel documents",
                    "Phone charger and power bank",
                    "Toiletry kit and personal medications",
                    "Reusable water bottle"
                ]
                return state

        if isinstance(items, list):
            state["packing_list"] = [str(it) for it in items]
        else:
            raise ValueError("Packing list output is not a list.")
    except Exception as err:
        state["errors"].append({"agent": "packing_agent", "message": str(err)})
        state["packing_list"] = [
            "Comfortable walking shoes",
            "Weather-appropriate clothing layers",
            "Passport and travel documents",
            "Phone charger and power bank",
            "Toiletry kit and personal medications",
            "Reusable water bottle"
        ]

    return state

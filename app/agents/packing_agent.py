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


_BASIC_FALLBACK = [
    "Passport / ID and printed booking confirmations", "Phone, charger and power bank", "Universal travel adapter",
    "Comfortable walking shoes", "Toiletries and personal medications", "Reusable water bottle",
    "Day backpack or cross-body bag", "Travel insurance details", "Some local cash and a backup card",
]


def _smart_fallback_packing(state) -> list:
    """Weather- and trip-aware checklist built in Python (used when the LLM is unavailable)."""
    items = list(_BASIC_FALLBACK)
    daily = ((state.get("weather") or {}).get("daily")) or []
    if daily:
        t_min = min(d.get("temp_min", 15) for d in daily)
        t_max = max(d.get("temp_max", 20) for d in daily)
        rain = sum(d.get("precipitation_mm", 0) for d in daily)
        if t_min < 10:
            items += ["Warm jacket", "Thermal layers", "Scarf and gloves"]
        elif t_min < 17:
            items += ["Light jacket or sweater", "Long trousers"]
        if t_max >= 26:
            items += ["Sunscreen and sunglasses", "Hat", "Light breathable clothing"]
        else:
            items += ["Layers you can add or remove"]
        if rain > 3:
            items += ["Compact umbrella", "Waterproof jacket", "Water-resistant shoes"]
    else:
        items += ["Layers for changing weather", "Compact umbrella"]
    ttype = state.get("trip_type", "leisure")
    extras = {
        "business": ["Formal outfits", "Laptop and charger", "Business cards"],
        "adventure": ["Sturdy hiking shoes", "First-aid kit", "Quick-dry clothing"],
        "family": ["Kids' snacks and essentials", "Basic medicines", "Entertainment for travel"],
        "romantic": ["One smart dinner outfit", "Camera"],
        "solo": ["Portable lock", "Emergency contact list"],
    }
    items += extras.get(ttype, ["Camera"])
    return items[:20]


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
                state["packing_list"] = _smart_fallback_packing(state)
                return state

        if isinstance(items, list):
            state["packing_list"] = [str(it) for it in items]
        else:
            raise ValueError("Packing list output is not a list.")
    except Exception as err:
        state["errors"].append({"agent": "packing_agent", "message": str(err)})
        state["packing_list"] = _smart_fallback_packing(state)

    return state

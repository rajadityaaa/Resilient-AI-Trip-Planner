"""
Weather Agent: Retrieves forecast or climate estimates for trip destination and dates.
"""
from app.agents.state import TripState
from app.tools.geocode_tools import geocode_place
from app.tools.weather_tools import get_forecast


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def get_weather(state: TripState) -> TripState:
    """
    Geocode trip destination and fetch weather forecast or climate estimate.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        # Check destination_suggestions if destination was not directly given
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "weather_agent", "message": "No destination specified or suggested."})
        state["weather"] = None
        return state

    try:
        geo = geocode_place(dest)
        start_date = state.get("start_date", "2026-09-01")
        end_date = state.get("end_date", "2026-09-05")

        weather_res = get_forecast(geo["lat"], geo["lon"], start_date, end_date)
        state["weather"] = weather_res
    except Exception as err:
        state["errors"].append({"agent": "weather_agent", "message": str(err)})
        state["weather"] = None

    return state

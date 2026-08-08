"""
Transport Agent: Generates transit, rideshare, walkability, and airport transfer guidance.
"""
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.transport_prompt import build_transport_prompt


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def build_transport_guide(state: TripState) -> TripState:
    """
    Generate local transport and transit guide for destination.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "transport_agent", "message": "No destination available."})
        state["transport_guide"] = None
        return state

    try:
        llm = get_llm()
        prompt = build_transport_prompt(dest)
        resp_text = llm(prompt)
        
        try:
            guide = clean_json_response(resp_text)
        except json.JSONDecodeError:
            # Retry once with stricter formatting instructions
            retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
            resp_text = llm(prompt + retry_instruction)
            try:
                guide = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Log a non-technical error and use fallback guide
                state["errors"].append({
                    "agent": "transport_agent",
                    "message": "transport_agent: LLM response could not be parsed after retry, using fallback guide"
                })
                state["transport_guide"] = {
                    "public_transit": "Information temporarily unavailable.",
                    "taxi_rideshare": "Information temporarily unavailable.",
                    "walkability": "Information temporarily unavailable.",
                    "airport_transfer": "Information temporarily unavailable.",
                    "tips": ["Information temporarily unavailable."]
                }
                return state

        if isinstance(guide, dict):
            # Ensure all expected keys exist to prevent downstream crashes
            expected_keys = ["public_transit", "taxi_rideshare", "walkability", "airport_transfer", "tips"]
            for k in expected_keys:
                if k not in guide or not guide[k]:
                    if k == "tips":
                        guide[k] = ["Information temporarily unavailable."]
                    else:
                        guide[k] = "Information temporarily unavailable."
            state["transport_guide"] = guide
        else:
            raise ValueError("Transport guide response is not a dict.")
    except Exception as err:
        state["errors"].append({"agent": "transport_agent", "message": str(err)})
        state["transport_guide"] = {
            "public_transit": f"Local metro and bus network available in {dest}.",
            "taxi_rideshare": "Rideshare apps and licensed taxis are widely available.",
            "walkability": "City center and major sight areas are easily walkable.",
            "airport_transfer": "Express buses and airport taxis connect main hubs.",
            "tips": ["Always check official taxi meters or negotiate fare before starting trip."]
        }

    return state

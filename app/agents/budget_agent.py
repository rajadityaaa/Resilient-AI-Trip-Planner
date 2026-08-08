"""
Budget Agent: Estimates and allocates trip budget across categories.
Rescales category values deterministically in Python if LLM sum deviates by > 1%.
"""
from datetime import datetime
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.budget_prompt import build_budget_prompt


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def build_budget(state: TripState) -> TripState:
    """
    Estimate realistic per-category budget split and validate total sum.
    """
    _init_errors(state)

    budget_total = float(state.get("budget_total", 1000.0))
    budget_currency = state.get("budget_currency", "USD")
    travelers = state.get("travelers", 1)

    # Calculate trip length in days
    try:
        s_date = datetime.strptime(state.get("start_date", "2026-09-01"), "%Y-%m-%d")
        e_date = datetime.strptime(state.get("end_date", "2026-09-05"), "%Y-%m-%d")
        num_days = max(1, (e_date - s_date).days)
    except Exception:
        num_days = 5

    try:
        llm = get_llm()
        prompt = build_budget_prompt(
            budget_total=budget_total,
            budget_currency=budget_currency,
            num_days=num_days,
            travelers=travelers,
            trip_type=state.get("trip_type", "leisure")
        )
        resp_text = llm(prompt)
        
        try:
            breakdown = clean_json_response(resp_text)
        except json.JSONDecodeError:
            # Retry once with stricter formatting instructions
            retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
            resp_text = llm(prompt + retry_instruction)
            try:
                breakdown = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Log a non-technical error and use fallback budget allocation
                state["errors"].append({
                    "agent": "budget_agent",
                    "message": "budget_agent: LLM response could not be parsed after retry, using fallback budget allocation"
                })
                state["budget_breakdown"] = {
                    "lodging": round(budget_total * 0.40, 2),
                    "food": round(budget_total * 0.25, 2),
                    "attractions": round(budget_total * 0.15, 2),
                    "transport": round(budget_total * 0.10, 2),
                    "buffer": round(budget_total * 0.10, 2)
                }
                return state

        if isinstance(breakdown, dict):
            # Ensure all 5 categories are present
            categories = ["lodging", "food", "attractions", "transport", "buffer"]
            for cat in categories:
                if cat not in breakdown:
                    breakdown[cat] = round(budget_total * 0.2, 2)

            # Validate total sum and proportionally rescale if off by > 1%
            current_sum = sum(float(breakdown[cat]) for cat in categories)
            if current_sum > 0 and abs(current_sum - budget_total) / budget_total > 0.01:
                factor = budget_total / current_sum
                breakdown = {cat: round(float(breakdown[cat]) * factor, 2) for cat in categories}

            state["budget_breakdown"] = breakdown
        else:
            raise ValueError("Budget breakdown response is not a dict.")
    except Exception as err:
        state["errors"].append({"agent": "budget_agent", "message": str(err)})
        # Safe default fallback allocation
        state["budget_breakdown"] = {
            "lodging": round(budget_total * 0.40, 2),
            "food": round(budget_total * 0.25, 2),
            "attractions": round(budget_total * 0.15, 2),
            "transport": round(budget_total * 0.10, 2),
            "buffer": round(budget_total * 0.10, 2)
        }

    return state

"""
CLI Test Harness for the full trip planner pipeline.
Not part of the Streamlit app — used to validate the entire LangGraph coordinator
before wiring up the UI.

Usage:
    python -m app.coordinator_test
"""
import asyncio
import json
import sys
import io

# Fix Windows console encoding for Unicode (Hindi, CJK, etc. in OSM data)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.agents.state import TripState
from app.agents.coordinator import plan_trip


def build_test_state() -> TripState:
    """Build a hardcoded TripState for Jaipur, India — 5 days, family trip, $1500."""
    return {
        "origin": "New Delhi",
        "destination": "Jaipur, India",
        "start_date": "2026-09-01",
        "end_date": "2026-09-05",
        "travelers": 4,
        "budget_total": 1500.0,
        "budget_currency": "USD",
        "trip_type": "family",
        "preferences": ["heritage", "museums", "street food", "hiking"],
        "destination_suggestions": None,
        "weather": None,
        "attractions": None,
        "restaurants": None,
        "hotels": None,
        "budget_breakdown": None,
        "transport_guide": None,
        "packing_list": None,
        "currency_info": None,
        "daily_itinerary": None,
        "errors": []
    }


def print_section(title: str, data, indent: int = 2):
    """Pretty-print a section of the final state."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    if data is None:
        print("  [No data available]")
    elif isinstance(data, (dict, list)):
        print(json.dumps(data, indent=indent, ensure_ascii=False, default=str))
    else:
        print(f"  {data}")


def main():
    print("\n" + "=" * 60)
    print("  TRAVEL PLANNER AGENT — CLI TEST HARNESS")
    print("=" * 60)

    state = build_test_state()
    print(f"\nTrip: {state['origin']} -> {state['destination']}")
    print(f"Dates: {state['start_date']} to {state['end_date']}")
    print(f"Travelers: {state['travelers']}, Budget: {state['budget_currency']} {state['budget_total']}")
    print(f"Type: {state['trip_type']}, Preferences: {state['preferences']}")
    print("\nRunning full pipeline...")

    final_state = asyncio.run(plan_trip(state))

    # Print results section by section
    print_section("WEATHER", final_state.get("weather"))
    print_section("ATTRACTIONS", final_state.get("attractions"))
    print_section("RESTAURANTS", final_state.get("restaurants"))
    print_section("HOTELS", final_state.get("hotels"))
    print_section("BUDGET BREAKDOWN", final_state.get("budget_breakdown"))
    print_section("TRANSPORT GUIDE", final_state.get("transport_guide"))
    print_section("PACKING LIST", final_state.get("packing_list"))
    print_section("CURRENCY INFO", final_state.get("currency_info"))
    print_section("DAILY ITINERARY", final_state.get("daily_itinerary"))

    # Print errors
    errors = final_state.get("errors", [])
    print_section("ERRORS", errors)
    if not errors:
        print("  No errors! Fully successful run.")
    else:
        print(f"  {len(errors)} error(s) logged (pipeline completed gracefully).")

    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60 + "\n")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

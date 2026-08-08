"""
CLI test harness for the full LangGraph trip planner pipeline.
Not part of the Streamlit app — used for end-to-end validation of the coordinator.

Usage:
    python coordinator_test.py
"""
import asyncio
import json
from app.agents.coordinator import plan_trip


def build_test_state() -> dict:
    """Build a hardcoded TripState for Jaipur, 5 days, family, $1500 budget."""
    return {
        "origin": "Delhi",
        "destination": "Bangkok",
        "start_date": "2026-08-10",
        "end_date": "2026-08-14",
        "travelers": 2,
        "budget_total": 1500.0,
        "budget_currency": "USD",
        "trip_type": "family",
        "preferences": ["heritage", "food", "culture"],
        # Agent outputs — all start as None
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
        "errors": [],
    }


def print_section(title: str, content, indent: int = 2):
    """Pretty-print a section of the final state."""
    prefix = " " * indent
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if content is None:
        print(f"{prefix}(not populated)")
    elif isinstance(content, (dict, list)):
        print(json.dumps(content, indent=indent, ensure_ascii=True))
    else:
        safe_content = str(content).encode('ascii', 'replace').decode()
        print(f"{prefix}{safe_content}")


async def main():
    state = build_test_state()
    print(f"Starting full pipeline for: {state['destination']}")
    print(f"  Dates: {state['start_date']} -> {state['end_date']}")
    print(f"  Budget: {state['budget_total']} {state['budget_currency']}")
    print(f"  Trip type: {state['trip_type']}, Travelers: {state['travelers']}")
    print(f"  Preferences: {state['preferences']}")
    print("-" * 60)

    final = await plan_trip(state)

    # ── Print agent outputs ──
    print_section("DESTINATION", final.get("destination"))
    print_section("WEATHER", final.get("weather"))

    attractions = final.get("attractions", [])
    print_section(f"ATTRACTIONS ({len(attractions)} found)", attractions)

    restaurants = final.get("restaurants", [])
    print_section(f"RESTAURANTS ({len(restaurants)} found)", restaurants)

    hotels = final.get("hotels", [])
    print_section(f"HOTELS ({len(hotels)} found)", hotels)

    print_section("BUDGET BREAKDOWN", final.get("budget_breakdown"))

    budget = final.get("budget_breakdown", {})
    if budget:
        total = sum(float(v) for v in budget.values())
        target = final.get("budget_total", 0)
        match = "OK - MATCH" if abs(total - target) < 1.0 else "XX - MISMATCH"
        print(f"\n  Budget sum: {total:.2f} vs target {target:.2f}  [{match}]")

    print_section("TRANSPORT GUIDE", final.get("transport_guide"))
    print_section("PACKING LIST", final.get("packing_list"))
    print_section("CURRENCY INFO", final.get("currency_info"))

    # ── Daily Itinerary (the main output) ──
    itinerary = final.get("daily_itinerary", [])
    print(f"\n{'='*60}")
    print(f"  DAILY ITINERARY ({len(itinerary)} days)")
    print(f"{'='*60}")
    if not itinerary:
        print("  (not populated)")
    if itinerary:
        first = itinerary[0]
        title = first.get("_trip_title", "(no title)")
        overview = first.get("_overview", "(no overview)")
        
        # Ensure strings are printed safely on Windows console
        def safe_print(label, val):
            safe_val = str(val).encode('ascii', 'replace').decode()
            print(f"{label}{safe_val}")

        safe_print("\n  Trip Title: ", title)
        safe_print("  Overview: ", overview)
        print()

        for day in itinerary:
            print(f"  --- Day {day.get('day', '?')} ({day.get('date', '?')}) ---")
            safe_print("    Morning:   ", day.get('morning', '(empty)'))
            safe_print("    Afternoon: ", day.get('afternoon', '(empty)'))
            safe_print("    Evening:   ", day.get('evening', '(empty)'))
            safe_print("    Notes:     ", day.get('notes', '(none)'))
            print()

    # ── Errors ──
    errors = final.get("errors", [])
    if errors:
        print_section(f"ERRORS ({len(errors)})", errors)
    else:
        print(f"\n  OK - No errors -- all agents completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())

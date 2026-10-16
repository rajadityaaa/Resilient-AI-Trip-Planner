"""
Scenario tests for coordinator.plan_trip covering real-world resilience:
- normal: end-to-end plan with simulated live responses.
- llm_down: LLM throws exceptions; deterministic fallbacks generate complete itinerary.
- overpass_down: Overpass fails/times out; Nominatim and AI fallbacks step in.
- all_apis_down: all external APIs and LLMs fail; fallbacks produce non-empty places and valid itinerary.
- one_agent_times_out: one agent exceeds timeout; coordinator recovers and finishes plan.
- two_plans_concurrently: two simultaneous plans run without state cross-contamination.
"""
from __future__ import annotations

import asyncio
import time
from typing import get_type_hints

import pytest

from app.agents.coordinator import plan_trip
from app.agents.state import TripState

SAMPLE_STATE: TripState = {
    "origin": "Delhi",
    "destination": "Bangkok, Thailand",
    "start_date": "2026-11-10",
    "end_date": "2026-11-12",  # 3 days: Nov 10, 11, 12
    "travelers": 2,
    "budget_total": 1500.0,
    "budget_currency": "USD",
    "trip_type": "leisure",
    "preferences": ["temples", "street food"],
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

EXPECTED_STATE_KEYS = set(get_type_hints(TripState).keys())


def _assert_trip_state_valid(result: dict, expected_days: int = 3):
    """Verify that result satisfies all TripState requirements."""
    # 1. Result has every key from TripState
    for key in EXPECTED_STATE_KEYS:
        assert key in result, f"Missing required TripState key '{key}'"

    # 2. daily_itinerary has one entry per day
    itinerary = result.get("daily_itinerary")
    assert isinstance(itinerary, list), "daily_itinerary must be a list"
    assert len(itinerary) == expected_days, (
        f"Expected {expected_days} days in itinerary, got {len(itinerary)}"
    )

    # 3. EVERY day has non-empty morning, afternoon, evening
    for day in itinerary:
        assert isinstance(day, dict), "Each day entry must be a dictionary"
        for slot in ("morning", "afternoon", "evening"):
            val = day.get(slot)
            assert isinstance(val, str) and val.strip(), (
                f"Day {day.get('day')} has empty or missing '{slot}' slot: {val!r}"
            )

    # 4. errors is a list
    assert isinstance(result.get("errors"), list)


# ── 1. Normal Scenario ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_trip_normal(fake_llm, fake_http, tmp_db):
    """End-to-end plan with mocked external services running smoothly."""
    start_time = time.time()
    result = await plan_trip(dict(SAMPLE_STATE))
    duration = time.time() - start_time

    _assert_trip_state_valid(result, expected_days=3)
    assert len(result["attractions"]) > 0, "Attractions should not be empty"
    assert len(result["restaurants"]) > 0, "Restaurants should not be empty"
    assert len(result["hotels"]) > 0, "Hotels should not be empty"
    assert duration < 5.0, f"Plan trip took too long with mocks: {duration:.2f}s"


# ── 2. LLM Down Scenario ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_trip_llm_down(fake_llm, fake_http, tmp_db):
    """When the LLM provider fails, deterministic fallbacks must construct the itinerary."""
    fake_llm.set_down(True)

    start_time = time.time()
    result = await plan_trip(dict(SAMPLE_STATE))
    duration = time.time() - start_time

    _assert_trip_state_valid(result, expected_days=3)
    # Errors logged due to LLM failure
    assert len(result["errors"]) > 0
    assert any("summary_agent" in e.get("message", "") for e in result["errors"])
    assert duration < 5.0, f"Plan trip took too long: {duration:.2f}s"


# ── 3. Overpass Down Scenario ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_trip_overpass_down(fake_llm, fake_http, tmp_db):
    """When Overpass fails or returns 504, the pipeline uses Nominatim / AI place fallbacks."""
    fake_http.set_overpass_down(mode="504")

    start_time = time.time()
    result = await plan_trip(dict(SAMPLE_STATE))
    duration = time.time() - start_time

    _assert_trip_state_valid(result, expected_days=3)
    assert len(result["attractions"]) > 0, "Attractions should fall back gracefully"
    assert len(result["restaurants"]) > 0, "Restaurants should fall back gracefully"
    assert duration < 5.0, f"Plan trip took too long: {duration:.2f}s"


# ── 4. All APIs Down Scenario ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_trip_all_apis_down(fake_llm, fake_http, tmp_db):
    """
    When all external HTTP APIs and LLMs fail simultaneously:
    - attractions, restaurants, and hotels lists must remain non-empty (fallbacks work).
    - daily_itinerary covers every day with morning/afternoon/evening.
    """
    fake_http.set_all_apis_down(True)
    fake_llm.set_down(True)

    start_time = time.time()
    result = await plan_trip(dict(SAMPLE_STATE))
    duration = time.time() - start_time

    _assert_trip_state_valid(result, expected_days=3)
    assert isinstance(result["attractions"], list) and len(result["attractions"]) > 0, (
        "Attractions list must be non-empty even when all APIs are down"
    )
    assert isinstance(result["restaurants"], list) and len(result["restaurants"]) > 0, (
        "Restaurants list must be non-empty even when all APIs are down"
    )
    assert isinstance(result["hotels"], list) and len(result["hotels"]) > 0, (
        "Hotels list must be non-empty even when all APIs are down"
    )
    assert duration < 5.0, f"Plan trip took too long: {duration:.2f}s"


# ── 5. One Agent Times Out Scenario ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_trip_one_agent_times_out(fake_llm, fake_http, tmp_db, monkeypatch):
    """
    If a single agent hangs or exceeds AGENT_TIMEOUT_S:
    - The coordinator thread times it out without stalling the graph.
    - All other agents finish, summary runs, and result is fully populated.
    """
    import app.agents.coordinator as coord

    async def _slow_currency(state: TripState) -> TripState:
        await asyncio.sleep(1.0)
        return state

    monkeypatch.setattr(coord, "AGENT_TIMEOUT_S", 0.4)
    monkeypatch.setitem(coord._OUTPUT_KEYS, "currency_info", _slow_currency)

    start_time = time.time()
    result = await plan_trip(dict(SAMPLE_STATE))
    duration = time.time() - start_time

    _assert_trip_state_valid(result, expected_days=3)
    # Check that error was logged for currency_info
    errs = [e for e in result["errors"] if e.get("agent") == "currency_info"]
    assert len(errs) > 0, f"Expected timeout error for currency_info, got: {result['errors']}"
    assert "TimeoutError" in errs[0].get("message", "")
    assert duration < 3.0, f"Coordinator stalled on timed-out agent: {duration:.2f}s"


# ── 6. Two Plans Concurrently Scenario ────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_trip_two_plans_concurrently(fake_llm, fake_http, tmp_db):
    """
    Run two plan_trip workflows concurrently:
    - Verifies that state is not leaked or shared between concurrent plans.
    """
    state_a = dict(SAMPLE_STATE)
    state_a["destination"] = "Bangkok, Thailand"

    state_b = dict(SAMPLE_STATE)
    state_b["destination"] = "Tokyo, Japan"
    state_b["preferences"] = ["anime", "sushi"]

    start_time = time.time()
    res_a, res_b = await asyncio.gather(
        plan_trip(state_a),
        plan_trip(state_b),
    )
    duration = time.time() - start_time

    _assert_trip_state_valid(res_a, expected_days=3)
    _assert_trip_state_valid(res_b, expected_days=3)

    assert "Bangkok" in res_a["destination"]
    assert "Tokyo" in res_b["destination"]
    assert duration < 5.0, f"Concurrent plans took too long: {duration:.2f}s"

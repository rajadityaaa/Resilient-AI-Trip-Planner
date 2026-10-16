"""
Tests for Step 6: Observability
Covers:
- Per-agent timing recording (done, warn, failed, timeout)
- Parallel start_offsets consistency
- Additive result guarantee (every old field intact + timings)
- Stats math on seeded rows and zero rows
- Percentile calculations
- Stats endpoint privacy (leaks no personal data)
- Metrics route absent unless enabled
- LangSmith tracing no-op when unconfigured
- Structured log lines with request_id, job_id, and secret masking
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agents.coordinator import plan_trip
from app.api.main import app, mount_metrics_route
from app.config import get_settings
from app.db import database as db
from app.observability.logging import (
    DevelopmentFormatter,
    StructuredJsonFormatter,
    current_job_id,
    current_request_id,
)
from app.observability.tracing import is_tracing_enabled, trace_run
from app.security.logging_filter import SecretMaskingFilter


@pytest.fixture
def test_client(tmp_db):
    """FastAPI TestClient backed by an isolated temporary database."""
    with TestClient(app) as client:
        yield client


# ── 1. Per-agent Timing & Result Completeness ─────────────────────────────────

@pytest.mark.asyncio
async def test_timing_recorded_for_agents(fake_llm, fake_http, tmp_db):
    """Verify timings are captured for all agents and old fields remain intact."""
    initial_state = {
        "destination": "Bangkok, Thailand",
        "origin": "London, UK",
        "start_date": "2026-11-01",
        "end_date": "2026-11-05",
        "budget_total": 2000.0,
        "budget_currency": "USD",
        "travelers_count": 2,
        "preferences": ["temples", "street food"],
        "pace": "medium",
    }

    result = await plan_trip(initial_state)

    # 1. Old fields must be present and unmodified
    expected_old_fields = [
        "destination",
        "daily_itinerary",
        "weather",
        "packing_list",
        "attractions",
        "restaurants",
        "hotels",
        "budget_breakdown",
        "transport_guide",
        "currency_info",
        "errors",
    ]
    for field in expected_old_fields:
        assert field in result, f"Missing expected field '{field}' in plan result"

    # 2. Timings field structure
    assert "timings" in result, "Result must contain new 'timings' field"
    timings = result["timings"]
    assert "total_duration_s" in timings
    assert isinstance(timings["total_duration_s"], float)
    assert timings["total_duration_s"] >= 0.0

    assert "critical_path" in timings
    assert isinstance(timings["critical_path"], list)
    assert len(timings["critical_path"]) >= 2
    assert timings["critical_path"][0] == "destination"
    assert timings["critical_path"][-1] == "summary"

    agents = timings["agents"]
    assert isinstance(agents, dict)

    # Check that major agents have full timing records
    required_agents = ["destination", "weather", "packing_list", "attractions", "restaurants", "hotels", "summary"]
    for agent_name in required_agents:
        assert agent_name in agents, f"Agent '{agent_name}' missing from timings"
        rec = agents[agent_name]
        assert rec["name"] == agent_name
        assert isinstance(rec["start_offset_s"], float)
        assert isinstance(rec["duration_s"], float)
        assert rec["duration_s"] >= 0.0
        assert rec["status"] in ("done", "warn", "failed", "timeout")
        assert isinstance(rec["fallback_used"], bool)
        assert "source" in rec
        assert "llm_model" in rec


@pytest.mark.asyncio
async def test_start_offsets_parallel_execution(fake_llm, fake_http, tmp_db):
    """Confirm parallel agents start around the same time while chains wait."""
    initial_state = {
        "destination": "Kyoto, Japan",
        "origin": "Paris, France",
        "start_date": "2026-10-01",
        "end_date": "2026-10-04",
        "budget_total": 1500.0,
        "travelers_count": 1,
        "preferences": ["gardens"],
    }

    result = await plan_trip(initial_state)
    agents = result["timings"]["agents"]

    dest_offset = agents["destination"]["start_offset_s"]
    weather_offset = agents["weather"]["start_offset_s"]
    attractions_offset = agents["attractions"]["start_offset_s"]
    restaurants_offset = agents["restaurants"]["start_offset_s"]
    packing_offset = agents["packing_list"]["start_offset_s"]

    # destination runs first
    assert dest_offset < weather_offset

    # weather, attractions, restaurants fan out in parallel, so their start offsets are very close
    assert abs(weather_offset - attractions_offset) < 0.2
    assert abs(attractions_offset - restaurants_offset) < 0.2

    # packing_list is chained after weather, so it must start after weather starts
    assert packing_offset >= weather_offset


@pytest.mark.asyncio
async def test_timing_recorded_on_agent_failure(fake_llm, fake_http, tmp_db, monkeypatch):
    """Verify timings are still recorded when an agent fails or times out."""
    async def broken_attractions(state):
        raise ValueError("Simulated attraction agent failure")

    from app.agents import coordinator
    monkeypatch.setitem(coordinator._OUTPUT_KEYS, "attractions", broken_attractions)

    initial_state = {
        "destination": "Rome, Italy",
        "start_date": "2026-09-01",
        "end_date": "2026-09-03",
    }

    result = await plan_trip(initial_state)
    agents = result["timings"]["agents"]

    assert "attractions" in agents
    att_timing = agents["attractions"]
    assert att_timing["status"] == "failed"
    assert att_timing["fallback_used"] is True
    assert att_timing["duration_s"] >= 0.0


@pytest.mark.asyncio
async def test_timing_recorded_on_agent_timeout(fake_llm, fake_http, tmp_db, monkeypatch):
    """Verify timeout status is recorded for an agent that exceeds AGENT_TIMEOUT_S."""
    async def slow_hotel(state):
        await asyncio.sleep(0.3)
        return {"hotels": []}

    from app.agents import coordinator
    monkeypatch.setitem(coordinator._OUTPUT_KEYS, "hotels", slow_hotel)
    monkeypatch.setattr("app.agents.coordinator.AGENT_TIMEOUT_S", 0.05)

    initial_state = {
        "destination": "Lisbon, Portugal",
        "start_date": "2026-09-01",
        "end_date": "2026-09-03",
    }

    result = await plan_trip(initial_state)
    agents = result["timings"]["agents"]

    assert "hotels" in agents
    hotel_timing = agents["hotels"]
    assert hotel_timing["status"] == "timeout"
    assert hotel_timing["fallback_used"] is True


# ── 2. Database Stats & Percentile Math ────────────────────────────────────────

def test_stats_math_zero_rows(tmp_db):
    """Test get_stats() on empty database returns sensible zeros."""
    stats = db.get_stats()
    assert stats["total_trips"] == 0
    assert stats["success_rate"] == 0.0
    assert stats["durations"] == {"p50": 0.0, "p95": 0.0, "avg": 0.0}
    assert stats["p50_duration_s"] == 0.0
    assert stats["p95_duration_s"] == 0.0
    assert stats["avg_duration_s"] == 0.0
    assert stats["average_duration_per_agent"] == {}
    assert stats["fallback_rate_per_agent"] == {}
    assert stats["llm_model_usage"] == {}
    assert stats["trips_last_24h"] == 0


def test_stats_math_seeded_rows(tmp_db):
    """Test stats math and percentile accuracy on seeded database rows."""
    now = time.time()
    durations = [2.0, 4.0, 6.0, 8.0, 10.0]

    for i, dur in enumerate(durations):
        status = "done" if i != 3 else "failed"
        timings_obj = {
            "total_duration_s": dur,
            "critical_path": ["destination", "weather", "summary"],
            "agents": {
                "weather": {
                    "name": "weather",
                    "duration_s": 0.5,
                    "status": "done",
                    "fallback_used": (i % 2 == 1),
                    "llm_model": "llama-3.3-70b-versatile",
                },
                "attractions": {
                    "name": "attractions",
                    "duration_s": 1.5,
                    "status": "done",
                    "fallback_used": False,
                    "llm_model": "openrouter/free",
                },
            },
        }
        db.save_trip(
            trip_id=f"trip-{i}",
            share_slug=f"slug-{i}",
            status=status,
            duration_s=dur,
            timings_obj=timings_obj,
            created_at=now - (i * 3600),  # all within last 5 hours (<24h)
        )

    stats = db.get_stats()

    assert stats["total_trips"] == 5
    assert stats["success_rate"] == 0.8  # 4 out of 5
    assert stats["trips_last_24h"] == 5

    # Durations: [2.0, 4.0, 6.0, 8.0, 10.0]
    # avg = 6.0
    # p50 = 6.0
    # p95 = 9.6
    assert stats["durations"]["avg"] == 6.0
    assert stats["durations"]["p50"] == 6.0
    assert stats["durations"]["p95"] == 9.6

    # Agent averages
    assert stats["average_duration_per_agent"]["weather"] == 0.5
    assert stats["average_duration_per_agent"]["attractions"] == 1.5

    # Fallback rate: weather was fallback in 2 out of 5 runs = 0.4
    assert stats["fallback_rate_per_agent"]["weather"] == 0.4
    assert stats["fallback_rate_per_agent"]["attractions"] == 0.0

    # Model usage
    assert stats["llm_model_usage"]["llama-3.3-70b-versatile"] == 5
    assert stats["llm_model_usage"]["openrouter/free"] == 5


# ── 3. API Privacy & Security ─────────────────────────────────────────────────

def test_stats_endpoint_privacy(test_client, tmp_db):
    """Ensure GET /api/stats never leaks personal user data (origin, destination, preferences)."""
    # Seed a trip with sensitive/personal strings
    secret_dest = "Secret_Confidential_Island"
    secret_origin = "Private_Personal_Residence"
    secret_pref = "very_confidential_preference"

    db.save_trip(
        trip_id="privacy-trip-1",
        share_slug="priv-slug-1",
        status="done",
        request_obj={
            "origin": secret_origin,
            "destination": secret_dest,
            "preferences": [secret_pref],
        },
        result_obj={
            "origin": secret_origin,
            "destination": secret_dest,
        },
        duration_s=3.45,
        timings_obj={
            "total_duration_s": 3.45,
            "critical_path": ["destination", "summary"],
            "agents": {
                "destination": {
                    "name": "destination",
                    "duration_s": 0.4,
                    "status": "done",
                    "fallback_used": False,
                    "llm_model": "mock-model",
                }
            },
        },
    )

    resp = test_client.get("/api/stats")
    assert resp.status_code == 200
    raw_text = resp.text

    # None of the private data should appear in the response
    assert secret_dest not in raw_text
    assert secret_origin not in raw_text
    assert secret_pref not in raw_text

    data = resp.json()
    assert data["total_trips"] == 1
    assert data["success_rate"] == 1.0
    assert "average_duration_per_agent" in data


# ── 4. Metrics Route Absent Unless Enabled ────────────────────────────────────

def test_metrics_route_absent_unless_enabled(test_client):
    """Confirm /metrics endpoint is 404 absent when ENABLE_METRICS=False, and present when True."""
    # When disabled (default)
    with patch.object(get_settings(), "ENABLE_METRICS", False):
        res = test_client.get("/metrics")
        assert res.status_code == 404

    # When enabled
    with patch.object(get_settings(), "ENABLE_METRICS", True):
        mount_metrics_route(app)
        res_enabled = test_client.get("/metrics")
        assert res_enabled.status_code == 200
        assert "travel_jobs_total" in res_enabled.text


# ── 5. LangSmith Tracing No-op ────────────────────────────────────────────────

def test_tracing_disabled_is_noop(monkeypatch):
    """Confirm tracing is strictly a no-op when unconfigured."""
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    assert not is_tracing_enabled()

    # Must complete with zero errors and zero network calls
    trace_run("test_run", inputs={"a": 1}, outputs={"b": 2})


# ── 6. Structured Logging & Secret Hygiene ─────────────────────────────────────

def test_structured_log_formatting_and_secret_hygiene():
    """Verify structured logs contain request_id/job_id and mask secret API keys."""
    # Set context variables
    r_token = current_request_id.set("req-test-123")
    j_token = current_job_id.set("job-test-456")

    try:
        formatter = StructuredJsonFormatter()
        filter_ = SecretMaskingFilter()

        # Fake API secret to test key masking
        fake_secret = "gsk_1234567890abcdef1234567890abcdef12345678"
        raw_msg = f"Connecting to Groq API with secret key: {fake_secret}"

        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg=raw_msg,
            args=(),
            exc_info=None,
        )

        # Apply filter and format
        filter_.filter(record)
        formatted = formatter.format(record)

        parsed = json.loads(formatted)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "app.test"
        assert parsed["request_id"] == "req-test-123"
        assert parsed["job_id"] == "job-test-456"
        assert "timestamp" in parsed

        # The fake secret must NEVER appear in the message
        assert fake_secret not in parsed["message"]
        assert "gsk_***" in parsed["message"]
    finally:
        current_request_id.reset(r_token)
        current_job_id.reset(j_token)


def test_development_formatter():
    """Verify DevelopmentFormatter includes context tags in plaintext."""
    r_token = current_request_id.set("req-abc")
    j_token = current_job_id.set("job-xyz")

    try:
        formatter = DevelopmentFormatter()
        record = logging.LogRecord(
            name="app.dev",
            level=logging.WARNING,
            pathname="dev.py",
            lineno=20,
            msg="Development debug test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "[WARNING]" in output
        assert "req:req-abc" in output
        assert "job:job-xyz" in output
        assert "Development debug test message" in output
    finally:
        current_request_id.reset(r_token)
        current_job_id.reset(j_token)

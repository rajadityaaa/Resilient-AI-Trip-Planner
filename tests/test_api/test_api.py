"""
Tests for the FastAPI backend (app/api/).

Strategy:
- Validation tests (sync): use FastAPI TestClient.
- Async tests: use httpx.AsyncClient with ASGITransport.
- coordinator.plan_trip is always monkeypatched – no LLMs or network calls.
- SSE test: uses a timeout so it doesn't hang waiting for disconnect.
- Progress tracker isolation: tested directly without HTTP.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import app.api.main as _main_module
from app.agents.progress import ProgressTracker, current_tracker
from app.api.jobs import create_job_manager
from app.api.main import app

# ── Shared test data ─────────────────────────────────────────────────────────

VALID_BODY = {
    "origin": "Delhi",
    "destination": "Bangkok",
    "start_date": "2026-11-10",
    "end_date": "2026-11-14",
    "travelers": 2,
    "budget_total": 2000,
    "budget_currency": "USD",
    "trip_type": "leisure",
    "preferences": ["temples", "street food"],
}

MINIMAL_RESULT = {
    "origin": "Delhi",
    "destination": "Bangkok",
    "daily_itinerary": [
        {
            "day": 1,
            "date": "2026-11-10",
            "morning": "Visit temples",
            "afternoon": "Street food tour",
            "evening": "River cruise",
            "notes": "Day 1 done",
        }
    ],
    "errors": [],
}


async def _fake_plan_trip(
    state: dict, progress_tracker: Optional[ProgressTracker] = None
) -> dict:
    """Instant drop-in for coordinator.plan_trip — no LLM / network calls."""
    tracker = progress_tracker or current_tracker.get()
    tracker.set_status("destination", "running")
    await asyncio.sleep(0.01)
    tracker.set_status("destination", "done", "Bangkok")
    tracker.set_status("weather", "done", "3 days")
    tracker.set_status("summary", "done", "1 day")
    result = dict(state)
    result.update(MINIMAL_RESULT)
    return result


def _transport():
    return httpx.ASGITransport(app=app)


# ── Autouse fixture: fresh store + manager per test ──────────────────────────

@pytest.fixture(autouse=True)
def _fresh_store():
    """Each test gets an isolated job store so jobs never bleed between tests."""
    store, manager = create_job_manager()
    _main_module._store = store
    _main_module._manager = manager
    yield


# ── 1. Validation errors (422) ───────────────────────────────────────────────

class TestValidation:
    """Synchronous validation via TestClient (no need for async)."""

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_missing_required_fields(self):
        assert self.client.post("/api/plan", json={}).status_code == 422

    def test_invalid_dates(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "start_date": "not-a-date"}).status_code == 422

    def test_end_before_start(self):
        body = {**VALID_BODY, "start_date": "2026-11-20", "end_date": "2026-11-10"}
        assert self.client.post("/api/plan", json=body).status_code == 422

    def test_trip_too_long(self):
        body = {**VALID_BODY, "start_date": "2026-01-01", "end_date": "2026-02-01"}
        assert self.client.post("/api/plan", json=body).status_code == 422

    def test_travelers_too_few(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "travelers": 0}).status_code == 422

    def test_travelers_too_many(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "travelers": 21}).status_code == 422

    def test_bad_currency(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "budget_currency": "us"}).status_code == 422

    def test_bad_trip_type(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "trip_type": "party"}).status_code == 422

    def test_too_many_preferences(self):
        body = {**VALID_BODY, "preferences": [f"p{i}" for i in range(11)]}
        assert self.client.post("/api/plan", json=body).status_code == 422

    def test_preference_too_long(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "preferences": ["x" * 51]}).status_code == 422

    def test_budget_zero(self):
        assert self.client.post("/api/plan", json={**VALID_BODY, "budget_total": 0}).status_code == 422


# ── 2. Full job lifecycle ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_job_lifecycle():
    """Submit a job, wait for it to finish, verify the result is in the store."""
    with patch("app.agents.coordinator.plan_trip", side_effect=_fake_plan_trip):
        # Directly call submit on the manager (no HTTP needed – avoids cross-loop issues)
        store = _main_module._store
        manager = _main_module._manager

        job_id = await manager.submit({
            **VALID_BODY,
            "destination_suggestions": None, "weather": None, "attractions": None,
            "restaurants": None, "hotels": None, "budget_breakdown": None,
            "transport_guide": None, "packing_list": None, "currency_info": None,
            "daily_itinerary": None, "errors": [],
        })

        # Poll the store until the job finishes (max 3 s)
        deadline = asyncio.get_event_loop().time() + 3
        while asyncio.get_event_loop().time() < deadline:
            job = store.get(job_id)
            if job and job.status in ("done", "failed"):
                break
            await asyncio.sleep(0.05)

        job = store.get(job_id)
        assert job is not None
        assert job.status == "done", f"Job status: {job.status}, error: {job.error}"
        assert job.result is not None
        assert "daily_itinerary" in job.result


# ── 3. 404 for unknown job ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_job_404():
    async with httpx.AsyncClient(transport=_transport(), base_url="http://test") as client:
        r = await client.get("/api/plan/does-not-exist-abc123xyz")
    assert r.status_code == 404


# ── 4. SSE stream: receives 'done' event ────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_stream_done_event():
    """Submit a job via the store directly and verify the SSE stream emits 'done'."""
    with patch("app.agents.coordinator.plan_trip", side_effect=_fake_plan_trip):
        store = _main_module._store
        manager = _main_module._manager

        request_dict = {
            **VALID_BODY,
            "destination_suggestions": None, "weather": None, "attractions": None,
            "restaurants": None, "hotels": None, "budget_breakdown": None,
            "transport_guide": None, "packing_list": None, "currency_info": None,
            "daily_itinerary": None, "errors": [],
        }
        job_id = await manager.submit(request_dict)

        events_seen: list[str] = []

        async def _collect_events():
            async with httpx.AsyncClient(transport=_transport(), base_url="http://test") as client:
                async with client.stream("GET", f"/api/plan/{job_id}/events") as stream:
                    async for line in stream.aiter_lines():
                        line = line.strip()
                        if line.startswith("event:"):
                            events_seen.append(line.split(":", 1)[1].strip())
                        if "done" in events_seen or "error" in events_seen:
                            return

        # Run with a 5-second guard so the test can't hang forever
        try:
            await asyncio.wait_for(_collect_events(), timeout=5.0)
        except asyncio.TimeoutError:
            pass  # we'll check events_seen below

        assert "done" in events_seen, f"SSE events received: {events_seen}"


# ── 5. Two concurrent jobs have independent progress trackers ─────────────────

@pytest.mark.asyncio
async def test_two_concurrent_jobs_independent_progress():
    """Each submitted job must get its own ProgressTracker instance."""
    captured_ids: list[int] = []

    async def _fake_capture(state: dict, progress_tracker: Optional[ProgressTracker] = None) -> dict:
        tracker = progress_tracker or current_tracker.get()
        captured_ids.append(id(tracker))
        tracker.set_status("destination", "done", state.get("destination", "?"))
        result = dict(state)
        result.update(MINIMAL_RESULT)
        return result

    with patch("app.agents.coordinator.plan_trip", side_effect=_fake_capture):
        manager = _main_module._manager
        base = {
            "destination_suggestions": None, "weather": None, "attractions": None,
            "restaurants": None, "hotels": None, "budget_breakdown": None,
            "transport_guide": None, "packing_list": None, "currency_info": None,
            "daily_itinerary": None, "errors": [],
        }
        id_a = await manager.submit({**VALID_BODY, "destination": "Paris", **base})
        id_b = await manager.submit({**VALID_BODY, "destination": "Tokyo", **base})

        # Wait for both jobs to complete
        deadline = asyncio.get_event_loop().time() + 3
        store = _main_module._store
        while asyncio.get_event_loop().time() < deadline:
            ja = store.get(id_a)
            jb = store.get(id_b)
            if ja and jb and ja.status in ("done", "failed") and jb.status in ("done", "failed"):
                break
            await asyncio.sleep(0.05)

    assert len(captured_ids) == 2, f"Expected 2 jobs, captured {len(captured_ids)}"
    assert captured_ids[0] != captured_ids[1], "Both jobs used the SAME ProgressTracker!"


# ── 6. /health does not leak secrets ────────────────────────────────────────

def test_health_no_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_supersecretkey12345")
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["llm_key_configured"], bool)
    assert "gsk_supersecretkey12345" not in r.text
    assert "supersecretkey" not in r.text


# ── 7. ProgressTracker isolation in worker threads ───────────────────────────

@pytest.mark.asyncio
async def test_progress_tracker_in_worker_threads():
    """
    asyncio.to_thread() must propagate the current_tracker ContextVar so
    worker threads write to the correct per-job tracker.
    """
    tracker_a = ProgressTracker()
    tracker_b = ProgressTracker()
    results: dict[str, dict] = {}

    async def _job(name: str, tracker: ProgressTracker) -> None:
        tok = current_tracker.set(tracker)
        try:
            def _worker() -> dict:
                from app.agents.progress import current_tracker as ct
                t = ct.get()
                t.set_status("destination", "done", name)
                snap, _ = t.snapshot()
                return snap

            snap = await asyncio.to_thread(_worker)
            results[name] = snap
        finally:
            current_tracker.reset(tok)

    await asyncio.gather(_job("JobA", tracker_a), _job("JobB", tracker_b))

    assert results["JobA"]["destination"]["detail"] == "JobA"
    assert results["JobB"]["destination"]["detail"] == "JobB"

    snap_a, _ = tracker_a.snapshot()
    snap_b, _ = tracker_b.snapshot()
    assert snap_a["destination"]["detail"] == "JobA"
    assert snap_b["destination"]["detail"] == "JobB"

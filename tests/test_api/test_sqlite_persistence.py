"""
Tests for Step 2: SQLite persistence, cache, SqliteJobStore, and saved/shareable trips.

Requirements covered:
1. TTL expiry in cache
2. Values survive a "restart" (new connection)
3. Concurrent writes from threads without database lock errors
4. Trip CRUD (create, read, update, list, delete)
5. Share link returns the same result and excludes origin/request details
6. Stale-running-jobs recovery on startup (running/queued -> failed with "server restarted")
7. Temp DB path per test
"""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.db.database as db
from app.api.jobs import Job, SqliteJobStore
from app.api.main import app
from app.tools.cache import _FALLBACK, cache_clear, cache_get, cache_set


# ── Fixture: Isolated temp DB per test ────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point DATABASE_URL to a fresh temporary SQLite file for each test."""
    db_file = tmp_path / "test_travel.db"
    monkeypatch.setenv("DATABASE_URL", str(db_file))
    # Clear path cache so init_db runs on the new file
    db._INITIALIZED_PATHS.clear()
    _FALLBACK.clear()
    db.init_db()
    yield str(db_file)
    # Cleanup
    _FALLBACK.clear()


# ── 1. TTL Expiry ─────────────────────────────────────────────────────────────

def test_cache_ttl_expiry():
    """Cache entry should be retrievable before expiry and None after TTL passes."""
    cache_set("ttl_key", {"data": "hello"}, ttl_seconds=1)
    assert cache_get("ttl_key") == {"data": "hello"}

    # Mock time in the future to test TTL expiry without sleeping
    with patch("time.time", return_value=time.time() + 2):
        assert cache_get("ttl_key") is None


def test_cache_purge_expired():
    """Opportunistic purge should remove expired entries from the DB."""
    # Write an already-expired entry
    db.cache_set_raw("expired_key", '{"v": 1}', expires_at=time.time() - 10)
    db.cache_set_raw("valid_key", '{"v": 2}', expires_at=time.time() + 300)

    deleted = db.cache_purge_expired()
    assert deleted >= 1
    assert db.cache_get_raw("expired_key") is None
    assert db.cache_get_raw("valid_key") is not None


# ── 2. Values survive a restart (new connection) ──────────────────────────────

def test_cache_values_survive_restart():
    """Values stored in SQLite survive when the in-memory fallback is cleared."""
    cache_set("survive_key", {"answer": 42}, ttl_seconds=3600)

    # Wipe in-memory fallback to simulate a brand-new process / connection
    _FALLBACK.clear()

    # Retrieve value - it must come directly from SQLite
    val = cache_get("survive_key")
    assert val == {"answer": 42}


def test_sqlite_job_store_survives_restart():
    """SqliteJobStore can retrieve jobs saved by a previous store instance."""
    store1 = SqliteJobStore()
    job = store1.create("job_restart_1", {"destination": "Kyoto", "days": 5})
    job.status = "done"
    job.result = {"itinerary": "day 1 temples"}
    store1.update(job)

    # Create a fresh store instance (simulates app restart)
    store2 = SqliteJobStore()
    loaded = store2.get("job_restart_1")
    assert loaded is not None
    assert loaded.job_id == "job_restart_1"
    assert loaded.status == "done"
    assert loaded.result == {"itinerary": "day 1 temples"}


# ── 3. Concurrent writes from threads ─────────────────────────────────────────

def test_concurrent_writes_threads():
    """Multiple threads writing to cache and trips simultaneously must not raise lock errors."""
    errors: list[Exception] = []

    def worker(worker_id: int):
        try:
            for i in range(15):
                key = f"thread_{worker_id}_key_{i}"
                cache_set(key, {"worker": worker_id, "i": i}, ttl_seconds=60)
                got = cache_get(key)
                assert got == {"worker": worker_id, "i": i}

                # Save trip
                db.save_trip(
                    trip_id=f"t_{worker_id}_{i}",
                    status="done",
                    request_obj={"dest": f"City_{worker_id}"},
                    result_obj={"days": i},
                )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent thread errors: {errors}"


# ── 4. Trip CRUD ──────────────────────────────────────────────────────────────

def test_trip_crud():
    """Test full Create, Read, Update, List, Delete lifecycle for trips."""
    # 1. Create
    slug = db.save_trip(
        trip_id="trip_crud_1",
        status="done",
        request_obj={"origin": "NYC", "destination": "Paris", "start_date": "2026-06-01"},
        result_obj={"destination": "Paris", "start_date": "2026-06-01", "end_date": "2026-06-07"},
    )
    assert slug is not None
    assert len(slug) == 10

    # 2. Read (by ID and by Slug)
    t = db.get_trip("trip_crud_1")
    assert t is not None
    assert t["id"] == "trip_crud_1"
    assert t["destination"] == "Paris"
    assert t["share_slug"] == slug

    t_slug = db.get_trip_by_slug(slug)
    assert t_slug is not None
    assert t_slug["id"] == "trip_crud_1"

    # 3. Update
    db.save_trip(
        trip_id="trip_crud_1",
        share_slug=slug,
        status="done",
        result_obj={"destination": "Paris Updated", "start_date": "2026-06-01"},
    )
    t_updated = db.get_trip("trip_crud_1")
    assert t_updated["result"]["destination"] == "Paris Updated"

    # 4. List
    trips = db.list_trips(limit=10)
    assert any(item["id"] == "trip_crud_1" for item in trips)
    crud_trip = next(item for item in trips if item["id"] == "trip_crud_1")
    assert "destination" in crud_trip
    assert "dates" in crud_trip
    assert "created_at" in crud_trip

    # 5. Delete
    deleted = db.delete_trip("trip_crud_1")
    assert deleted is True
    assert db.get_trip("trip_crud_1") is None
    # Delete non-existent
    assert db.delete_trip("trip_crud_1") is False


# ── 5. Share link returns the same result and excludes origin ────────────────

def test_share_link_returns_same_result():
    """Public share endpoint returns the same result and excludes origin/request details."""
    trip_id = "trip_share_test"
    request_data = {"origin": "London", "destination": "Rome", "start_date": "2026-08-01"}
    result_data = {
        "destination": "Rome",
        "daily_itinerary": [{"day": 1, "activity": "Colosseum"}],
        "origin": "London",  # coordinator might have origin in state
    }

    slug = db.save_trip(
        trip_id=trip_id,
        status="done",
        request_obj=request_data,
        result_obj=result_data,
    )

    client = TestClient(app, raise_server_exceptions=False)

    # 1. Full trip endpoint includes request and details
    full_resp = client.get(f"/api/trips/{trip_id}")
    assert full_resp.status_code == 200
    full_trip = full_resp.json()
    assert full_trip["id"] == trip_id
    assert full_trip["request"]["origin"] == "London"

    # 2. Public share endpoint excludes origin / request details
    share_resp = client.get(f"/api/share/{slug}")
    assert share_resp.status_code == 200
    share_data = share_resp.json()

    assert share_data["id"] == trip_id
    assert share_data["share_slug"] == slug
    assert "request" not in share_data
    # Origin should not be present at top level or in result
    assert "origin" not in share_data
    if "result" in share_data and share_data["result"]:
        assert "origin" not in share_data["result"]
        # Itinerary and other results match
        assert share_data["result"]["daily_itinerary"] == result_data["daily_itinerary"]


def test_share_link_404_for_unknown_slug():
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/share/non_existent_slug_xyz")
    assert resp.status_code == 404


# ── 6. Stale-running-jobs recovery ───────────────────────────────────────────

def test_stale_running_jobs_recovery():
    """Jobs in running or queued status on startup are marked failed with 'server restarted'."""
    db.save_trip("stale_job_1", status="running", request_obj={"dest": "Berlin"})
    db.save_trip("stale_job_2", status="queued", request_obj={"dest": "Tokyo"})
    db.save_trip("done_job_3", status="done", request_obj={"dest": "Oslo"})

    # Trigger recovery as happens on SqliteJobStore startup
    store = SqliteJobStore()

    job1 = store.get("stale_job_1")
    assert job1 is not None
    assert job1.status == "failed"
    assert job1.error == "server restarted"

    job2 = store.get("stale_job_2")
    assert job2 is not None
    assert job2.status == "failed"
    assert job2.error == "server restarted"

    job3 = store.get("done_job_3")
    assert job3 is not None
    assert job3.status == "done"


# ── 7. FastAPI Trips API Endpoints ────────────────────────────────────────────

def test_trips_api_endpoints():
    """Test /api/trips list, get, and delete endpoints."""
    client = TestClient(app, raise_server_exceptions=False)

    # Save a finished trip
    slug = db.save_trip(
        trip_id="api_trip_1",
        status="done",
        request_obj={"destination": "Madrid", "start_date": "2026-09-01", "end_date": "2026-09-05"},
        result_obj={"destination": "Madrid", "start_date": "2026-09-01", "end_date": "2026-09-05"},
    )

    # GET /api/trips
    res_list = client.get("/api/trips")
    assert res_list.status_code == 200
    trips = res_list.json()
    assert isinstance(trips, list)
    matching = [t for t in trips if t["id"] == "api_trip_1"]
    assert len(matching) == 1
    assert matching[0]["destination"] == "Madrid"
    assert matching[0]["dates"] == "2026-09-01 to 2026-09-05"

    # GET /api/trips/{id}
    res_get = client.get("/api/trips/api_trip_1")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == "api_trip_1"
    assert res_get.json()["share_slug"] == slug

    # GET /api/trips/unknown -> 404
    assert client.get("/api/trips/unknown_trip_xyz").status_code == 404

    # DELETE /api/trips/{id}
    res_del = client.delete("/api/trips/api_trip_1")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # Confirm deleted
    assert client.get("/api/trips/api_trip_1").status_code == 404
    assert client.delete("/api/trips/api_trip_1").status_code == 404

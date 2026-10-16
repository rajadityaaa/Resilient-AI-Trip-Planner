"""
SQLite persistence layer for the Travel Planner Agent.

Design rules:
- DB path from env DATABASE_URL (default: data/travel.db). Creates the folder automatically.
- Thread-safe: every public function opens its own short-lived connection and closes it on return.
  This is safe because SQLite's WAL mode allows many concurrent readers + one writer.
- WAL mode + busy_timeout so threads never see "database is locked" under normal load.
- Tables (created if not exist): cache, trips, schema_version.
- Zero external dependencies – stdlib sqlite3 only.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_SCHEMA_VERSION = 1          # bump when DDL changes
_BUSY_TIMEOUT_MS = 5_000     # ms to wait when DB is locked
_INITIALIZED_PATHS: set[str] = set()


def _db_path() -> Path:
    """Resolve the DB file path, creating the parent directory if needed."""
    from app.config import get_settings
    raw = os.getenv("DATABASE_URL") or get_settings().DATABASE_URL
    if raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///"):]
    p = Path(raw)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── DDL / migrations ──────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create tables and run simple integer-versioned migrations.
    Safe to call multiple times (idempotent).
    """
    p = _db_path()
    conn = sqlite3.connect(str(p), timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current = row["version"] if row else 0

        if current < 1:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key        TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trips (
                    id           TEXT PRIMARY KEY,
                    share_slug   TEXT UNIQUE NOT NULL,
                    created_at   REAL NOT NULL,
                    status       TEXT NOT NULL,
                    request_json TEXT,
                    result_json  TEXT,
                    errors_json  TEXT,
                    duration_s   REAL,
                    timings_json TEXT
                );
                """
            )
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version VALUES (?)", (_SCHEMA_VERSION,))
            conn.commit()
            logger.info(f"[DB] Database initialised (schema v{_SCHEMA_VERSION}).")
    except Exception as exc:
        logger.error(f"[DB] init_db failed: {exc}")
        raise
    finally:
        conn.close()


# ── Connection context manager ────────────────────────────────────────────────

@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    """
    Open a short-lived SQLite connection in WAL mode.
    Always closes the connection, even on error.
    """
    p = _db_path()
    p_str = str(p.resolve())
    if p_str not in _INITIALIZED_PATHS:
        init_db()
        _INITIALIZED_PATHS.add(p_str)

    try:
        conn = sqlite3.connect(str(p), timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"[DB] Failed to open SQLite connection: {exc}")
        raise


# ── Cache helpers ─────────────────────────────────────────────────────────────

def cache_get_raw(key: str) -> Optional[str]:
    """Return raw JSON string if the cache key exists and has not expired."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT value_json FROM cache WHERE key = ? AND expires_at > ?",
            (key, time.time()),
        ).fetchone()
        return row["value_json"] if row else None


def cache_set_raw(key: str, value_json: str, expires_at: float) -> None:
    """Upsert a raw JSON string into the cache table."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO cache (key, value_json, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                                           expires_at=excluded.expires_at
            """,
            (key, value_json, expires_at),
        )
        conn.commit()


def cache_purge_expired() -> int:
    """Delete expired cache rows. Returns number of rows deleted."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM cache WHERE expires_at <= ?", (time.time(),)
        )
        conn.commit()
        return cur.rowcount


def cache_clear_all() -> None:
    """Delete ALL cache rows (used by cache_clear())."""
    with _connect() as conn:
        conn.execute("DELETE FROM cache")
        conn.commit()


# ── Trip helpers ──────────────────────────────────────────────────────────────

def save_trip(
    trip_id: str,
    share_slug: Optional[str] = None,
    status: str = "done",
    request_obj: Optional[dict] = None,
    result_obj: Optional[dict] = None,
    errors_obj: Optional[list] = None,
    duration_s: Optional[float] = None,
    timings_obj: Optional[dict] = None,
    created_at: Optional[float] = None,
) -> str:
    """
    Insert or replace a trip row.
    Preserves existing created_at and share_slug if already present in DB.
    Returns the share_slug.
    """
    with _connect() as conn:
        existing = conn.execute(
            "SELECT created_at, share_slug FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()

        now = time.time()
        final_created_at = created_at or (existing["created_at"] if existing else now)
        final_slug = share_slug or (
            existing["share_slug"] if existing else secrets.token_urlsafe(8)[:10]
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO trips
                (id, share_slug, created_at, status, request_json, result_json,
                 errors_json, duration_s, timings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                final_slug,
                final_created_at,
                status,
                json.dumps(request_obj) if request_obj is not None else None,
                json.dumps(result_obj) if result_obj is not None else None,
                json.dumps(errors_obj) if errors_obj is not None else None,
                duration_s,
                json.dumps(timings_obj) if timings_obj is not None else None,
            ),
        )
        conn.commit()
        return final_slug


def get_trip(trip_id: str) -> Optional[dict]:
    """Return a full trip dict or None."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        return _row_to_trip(row) if row else None


def get_trip_by_slug(slug: str) -> Optional[dict]:
    """Return a full trip dict by share_slug or None."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM trips WHERE share_slug = ?", (slug,)).fetchone()
        return _row_to_trip(row) if row else None


def list_trips(limit: int = 20) -> list[dict]:
    """Return last ``limit`` finished trips (id, destination, dates, created_at)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, share_slug, created_at, status, request_json, result_json
            FROM trips
            WHERE status IN ('done', 'failed', 'finished')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_summary(r) for r in rows]


def delete_trip(trip_id: str) -> bool:
    """Delete a trip by id. Returns True if a row was deleted."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        conn.commit()
        return cur.rowcount > 0


def get_daily_trip_count(window_seconds: float = 86400) -> int:
    """Return count of trip plans submitted within the last window_seconds (default 24h)."""
    cutoff = time.time() - window_seconds
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM trips WHERE created_at >= ?", (cutoff,)).fetchone()
        return row[0] if row else 0


def _compute_percentile(data: list[float], p: float) -> float:
    """Compute p-th percentile (0.0 to 1.0) with linear interpolation."""
    if not data:
        return 0.0
    sorted_d = sorted(data)
    n = len(sorted_d)
    if n == 1:
        return round(float(sorted_d[0]), 3)
    k = (n - 1) * p
    f = int(k)
    c = min(f + 1, n - 1)
    d = k - f
    val = sorted_d[f] + d * (sorted_d[c] - sorted_d[f])
    return round(float(val), 3)


def get_stats() -> dict[str, Any]:
    """
    Compute aggregate platform statistics from the trips table.
    Contains no personal data (no origin, destination, preferences, dates).
    Returns sensible zeros if there are no trips.
    """
    cutoff_24h = time.time() - 86400.0

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT status, duration_s, created_at, timings_json
            FROM trips
            """
        ).fetchall()

    total_trips = len(rows)
    if total_trips == 0:
        return {
            "total_trips": 0,
            "success_rate": 0.0,
            "durations": {"p50": 0.0, "p95": 0.0, "avg": 0.0},
            "p50_duration_s": 0.0,
            "p95_duration_s": 0.0,
            "avg_duration_s": 0.0,
            "average_duration_per_agent": {},
            "fallback_rate_per_agent": {},
            "llm_model_usage": {},
            "trips_last_24h": 0,
        }

    successful = 0
    durations: list[float] = []
    trips_24h = 0

    agent_durations: dict[str, list[float]] = {}
    agent_fallbacks: dict[str, list[bool]] = {}
    model_usage: dict[str, int] = {}

    for row in rows:
        st = row["status"]
        if st in ("done", "finished"):
            successful += 1

        dur = row["duration_s"]
        if dur is not None and isinstance(dur, (int, float)) and dur >= 0:
            durations.append(float(dur))

        created = row["created_at"]
        if created is not None and float(created) >= cutoff_24h:
            trips_24h += 1

        raw_timings = row["timings_json"]
        if raw_timings:
            try:
                t_obj = json.loads(raw_timings) if isinstance(raw_timings, str) else raw_timings
                if isinstance(t_obj, dict):
                    agents_map = t_obj.get("agents") or {}
                    for a_name, a_info in agents_map.items():
                        if not isinstance(a_info, dict):
                            continue
                        a_dur = a_info.get("duration_s")
                        if a_dur is not None and isinstance(a_dur, (int, float)):
                            agent_durations.setdefault(a_name, []).append(float(a_dur))

                        fb = bool(a_info.get("fallback_used"))
                        agent_fallbacks.setdefault(a_name, []).append(fb)

                        m = a_info.get("llm_model")
                        if m and isinstance(m, str):
                            model_usage[m] = model_usage.get(m, 0) + 1
            except Exception:
                pass

    success_rate = round(successful / total_trips, 4)

    if durations:
        p50 = _compute_percentile(durations, 0.50)
        p95 = _compute_percentile(durations, 0.95)
        avg = round(sum(durations) / len(durations), 3)
    else:
        p50 = 0.0
        p95 = 0.0
        avg = 0.0

    avg_agent_dur = {
        name: round(sum(d_list) / len(d_list), 3)
        for name, d_list in agent_durations.items()
        if d_list
    }

    fb_rate_agent = {
        name: round(sum(1 for x in fb_list if x) / len(fb_list), 4)
        for name, fb_list in agent_fallbacks.items()
        if fb_list
    }

    return {
        "total_trips": total_trips,
        "success_rate": success_rate,
        "durations": {"p50": p50, "p95": p95, "avg": avg},
        "p50_duration_s": p50,
        "p95_duration_s": p95,
        "avg_duration_s": avg,
        "average_duration_per_agent": avg_agent_dur,
        "fallback_rate_per_agent": fb_rate_agent,
        "llm_model_usage": model_usage,
        "trips_last_24h": trips_24h,
    }


def recover_stale_jobs() -> int:
    """
    Mark any running/queued jobs as failed with message 'server restarted'.
    Returns number of rows updated.
    """
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE trips
            SET status = 'failed',
                errors_json = '["server restarted"]'
            WHERE status IN ('running', 'queued')
            """
        )
        conn.commit()
        return cur.rowcount


# ── Row parsers ───────────────────────────────────────────────────────────────

def _row_to_trip(row: sqlite3.Row) -> dict:
    request = _safe_json(row["request_json"])
    result = _safe_json(row["result_json"])
    errors = _safe_json(row["errors_json"]) or []
    timings = _safe_json(row["timings_json"])

    destination = (result or {}).get("destination") or (request or {}).get("destination")
    start_date = (result or {}).get("start_date") or (request or {}).get("start_date")
    end_date = (result or {}).get("end_date") or (request or {}).get("end_date")
    dates = f"{start_date} to {end_date}".strip(" to ") if (start_date or end_date) else ""

    return {
        "id": row["id"],
        "share_slug": row["share_slug"],
        "created_at": row["created_at"],
        "status": row["status"],
        "request": request,
        "result": result,
        "errors": errors,
        "duration_s": row["duration_s"],
        "timings": timings,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "dates": dates,
    }


def _row_to_summary(row: sqlite3.Row) -> dict:
    request = _safe_json(row["request_json"])
    result = _safe_json(row["result_json"])

    destination = (result or {}).get("destination") or (request or {}).get("destination") or ""
    start_date = (result or {}).get("start_date") or (request or {}).get("start_date") or ""
    end_date = (result or {}).get("end_date") or (request or {}).get("end_date") or ""
    dates = f"{start_date} to {end_date}".strip(" to ") if (start_date or end_date) else ""

    return {
        "id": row["id"],
        "destination": destination,
        "dates": dates,
        "created_at": row["created_at"],
        "share_slug": row["share_slug"],
        "status": row["status"],
    }


def _safe_json(text: Optional[str]) -> Optional[object]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None

"""
Job management for the Travel Planner API.

Provides:
- JobStore protocol  – create / get / update / list
- InMemoryJobStore   – thread-safe, 1-hour TTL auto-cleanup (used in tests)
- SqliteJobStore     – persistent, survives server restarts
- JobManager         – runs plan_trip as asyncio tasks, limits to 3 concurrent jobs,
                       queues extras and starts them as slots free up.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_JOB_TTL_S = 3600  # 1 hour
_MAX_CONCURRENT = 3


# ── Data class ────────────────────────────────────────────────────────────────

class Job:
    """Mutable job record stored by any JobStore implementation."""

    __slots__ = (
        "job_id", "status", "created_at", "started_at", "finished_at",
        "request", "result", "error", "_tracker", "share_slug",
    )

    def __init__(self, job_id: str, request: dict) -> None:
        self.job_id: str = job_id
        self.status: str = "queued"
        self.created_at: float = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.request: dict = request
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._tracker: Optional[object] = None  # set by JobManager._execute for SSE polling
        self.share_slug: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "share_slug": self.share_slug,
        }


# ── Protocol ──────────────────────────────────────────────────────────────────

@runtime_checkable
class JobStore(Protocol):
    def create(self, job_id: str, request: dict) -> Job: ...
    def get(self, job_id: str) -> Optional[Job]: ...
    def update(self, job: Job) -> None: ...
    def list_recent(self, limit: int = 20) -> list[Job]: ...


# ── In-memory implementation (used in tests) ──────────────────────────────────

class InMemoryJobStore:
    """Thread-safe in-memory job store with 1-hour TTL cleanup."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, request: dict) -> Job:
        job = Job(job_id, request)
        job.share_slug = secrets.token_urlsafe(8)[:10]
        with self._lock:
            self._jobs[job_id] = job
            self._purge_expired()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def list_recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            finished = [j for j in self._jobs.values() if j.status in ("done", "failed")]
        finished.sort(key=lambda j: j.created_at, reverse=True)
        return finished[:limit]

    def _purge_expired(self) -> None:
        """Remove jobs older than TTL. Must be called while holding self._lock."""
        cutoff = time.time() - _JOB_TTL_S
        expired = [jid for jid, j in self._jobs.items() if j.created_at < cutoff]
        for jid in expired:
            del self._jobs[jid]


# ── SQLite implementation ─────────────────────────────────────────────────────

class SqliteJobStore:
    """
    Persistent job store backed by SQLite (app.db.database).

    Jobs are stored in:
    - The SQLite trips table for durable persistence (survives restarts).
    - An in-memory dict for low-overhead SSE polling during active execution.

    On startup, any job still in status 'running' or 'queued' is marked
    'failed' with message 'server restarted'.
    """

    def __init__(self) -> None:
        self._live: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._recover_stale_jobs()

    # ── JobStore interface ────────────────────────────────────────────────────

    def create(self, job_id: str, request: dict) -> Job:
        job = Job(job_id, request)
        job.share_slug = secrets.token_urlsafe(8)[:10]
        with self._lock:
            self._live[job_id] = job
        self._persist(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            live = self._live.get(job_id)
        if live is not None:
            return live
        return self._load(job_id)

    def update(self, job: Job) -> None:
        with self._lock:
            self._live[job.job_id] = job
        self._persist(job)

    def list_recent(self, limit: int = 20) -> list[Job]:
        from app.db import database as db
        try:
            summaries = db.list_trips(limit)
            return [self._summary_to_job(s) for s in summaries]
        except Exception as exc:
            logger.error(f"[SqliteJobStore] list_recent error: {exc}")
            return []

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _persist(self, job: Job) -> None:
        from app.db import database as db
        errors = []
        if job.error:
            errors.append(job.error)
        elif job.result and isinstance(job.result, dict) and job.result.get("errors"):
            errors.extend(job.result.get("errors"))

        duration_s = None
        if job.finished_at and job.started_at:
            duration_s = round(job.finished_at - job.started_at, 3)

        try:
            slug = db.save_trip(
                trip_id=job.job_id,
                share_slug=job.share_slug,
                status=job.status,
                request_obj=job.request,
                result_obj=job.result,
                errors_obj=errors if errors else None,
                duration_s=duration_s,
                timings_obj=None,
                created_at=job.created_at,
            )
            job.share_slug = slug
        except Exception as exc:
            logger.error(f"[SqliteJobStore] Failed to persist job {job.job_id}: {exc}")

    def _load(self, job_id: str) -> Optional[Job]:
        from app.db import database as db
        try:
            row = db.get_trip(job_id)
            if row is None:
                return None
            return self._row_to_job(row)
        except Exception as exc:
            logger.error(f"[SqliteJobStore] Failed to load job {job_id}: {exc}")
            return None

    def _row_to_job(self, row: dict) -> Job:
        job = Job(row["id"], row.get("request") or {})
        job.share_slug = row.get("share_slug")
        job.status = row["status"]
        job.created_at = row["created_at"]
        job.result = row.get("result")
        errors = row.get("errors") or []
        if errors:
            job.error = str(errors[0]) if isinstance(errors, list) else str(errors)
        else:
            job.error = None
        return job

    def _summary_to_job(self, summary: dict) -> Job:
        job = Job(summary["id"], {})
        job.share_slug = summary.get("share_slug")
        job.status = summary.get("status", "done")
        job.created_at = summary.get("created_at", time.time())
        return job

    def _recover_stale_jobs(self) -> None:
        """Mark any running/queued jobs as failed with message 'server restarted'."""
        from app.db import database as db
        try:
            count = db.recover_stale_jobs()
            if count:
                logger.info(f"[SqliteJobStore] Recovered {count} stale jobs -> failed.")
        except Exception as exc:
            logger.warning(f"[SqliteJobStore] Stale job recovery failed: {exc}")


# ── Job Manager ───────────────────────────────────────────────────────────────

class JobManager:
    """
    Coordinates job scheduling and execution.
    Limits concurrency to _MAX_CONCURRENT simultaneous tasks.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self._semaphore: Optional[asyncio.Semaphore] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazily create the semaphore on the running event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        return self._semaphore

    async def submit(self, request: dict) -> str:
        """
        Create a new job and schedule it. Returns the job_id immediately (202).
        Short ID is 10 url-safe chars.
        """
        from app.agents.progress import ProgressTracker

        job_id = secrets.token_urlsafe(8)[:10]
        job = self._store.create(job_id, request)

        asyncio.create_task(self._run_job(job, ProgressTracker()))
        return job_id

    async def _run_job(self, job: Job, tracker: "ProgressTracker") -> None:
        """Acquire concurrency semaphore then execute the job."""
        sem = self._get_semaphore()
        async with sem:
            await self._execute(job, tracker)

    async def _execute(self, job: Job, tracker: "ProgressTracker") -> None:
        """Call plan_trip and update the job record."""
        from app.agents.coordinator import plan_trip

        job._tracker = tracker  # type: ignore[attr-defined]

        job.status = "running"
        job.started_at = time.time()
        self._store.update(job)
        logger.info(f"[JobManager] Job {job.job_id} started.")

        try:
            result = await plan_trip(job.request, progress_tracker=tracker)
            job.status = "done"
            job.result = result
            logger.info(f"[JobManager] Job {job.job_id} completed successfully.")
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            logger.exception(f"[JobManager] Job {job.job_id} failed: {exc}")
        finally:
            job.finished_at = time.time()
            self._store.update(job)


# ── Factory functions ─────────────────────────────────────────────────────────

def create_job_manager() -> tuple[InMemoryJobStore, JobManager]:
    """Convenience factory for tests using in-memory store."""
    store = InMemoryJobStore()
    manager = JobManager(store)
    return store, manager


def create_sqlite_job_manager() -> tuple[SqliteJobStore, JobManager]:
    """Factory for production and persistence tests using SQLite."""
    store = SqliteJobStore()
    manager = JobManager(store)
    return store, manager

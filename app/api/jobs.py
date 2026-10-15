"""
Job management for the Travel Planner API.

Provides:
- JobStore protocol  – create / get / update / list
- InMemoryJobStore   – thread-safe, 1-hour TTL auto-cleanup
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


# ── Data class ───────────────────────────────────────────────────────────────

class Job:
    """Mutable job record stored by the job store."""

    __slots__ = (
        "job_id", "status", "created_at", "started_at", "finished_at",
        "request", "result", "error", "_tracker",
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


# ── Protocol ─────────────────────────────────────────────────────────────────

@runtime_checkable
class JobStore(Protocol):
    def create(self, job_id: str, request: dict) -> Job: ...
    def get(self, job_id: str) -> Optional[Job]: ...
    def update(self, job: Job) -> None: ...
    def list_recent(self, limit: int = 20) -> list[Job]: ...


# ── In-memory implementation ─────────────────────────────────────────────────

class InMemoryJobStore:
    """Thread-safe in-memory job store with 1-hour TTL cleanup."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # ── JobStore interface ───────────────────────────────────────────────────

    def create(self, job_id: str, request: dict) -> Job:
        job = Job(job_id, request)
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
            finished = [
                j for j in self._jobs.values()
                if j.status in ("done", "failed")
            ]
        finished.sort(key=lambda j: j.created_at, reverse=True)
        return finished[:limit]

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _purge_expired(self) -> None:
        """Remove jobs older than TTL. Must be called while holding self._lock."""
        cutoff = time.time() - _JOB_TTL_S
        expired = [jid for jid, j in self._jobs.items() if j.created_at < cutoff]
        for jid in expired:
            del self._jobs[jid]


# ── Job Manager ───────────────────────────────────────────────────────────────

class JobManager:
    """
    Runs ``plan_trip`` as asyncio tasks.

    - At most ``_MAX_CONCURRENT`` jobs run simultaneously.
    - Extra submitted jobs stay in ``queued`` state and are started as slots free.
    - Progress tracking is per-job via a dedicated ``ProgressTracker`` instance,
      passed into ``plan_trip`` as the optional ``progress_tracker`` kwarg.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._started = False

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazily create the semaphore on the running event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        return self._semaphore

    async def submit(self, request: dict) -> str:
        """
        Create a new job and schedule it.  Returns the job_id immediately (202).
        """
        from app.agents.progress import ProgressTracker  # avoid circular import at module load

        job_id = secrets.token_urlsafe(12)
        job = self._store.create(job_id, request)

        asyncio.create_task(self._run_job(job, ProgressTracker()))
        return job_id

    async def _run_job(self, job: Job, tracker: "ProgressTracker") -> None:
        """Acquire the concurrency semaphore, run the job, release, then drain the queue."""
        sem = self._get_semaphore()
        # Mark queued while waiting
        async with sem:
            await self._execute(job, tracker)

    async def _execute(self, job: Job, tracker: "ProgressTracker") -> None:
        """Actually call plan_trip, update the job record."""
        from app.agents.coordinator import plan_trip  # late import – coordinator is heavy

        # Attach tracker to the job so the SSE endpoint can poll it.
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


# ── Module-level singleton (replaced per-app in main.py) ─────────────────────

def create_job_manager() -> tuple[InMemoryJobStore, JobManager]:
    """Convenience factory used by the FastAPI app on startup."""
    store = InMemoryJobStore()
    manager = JobManager(store)
    return store, manager

"""
FastAPI application for the Travel Planner Agent.

Endpoints
---------
POST   /api/plan                  – submit a new planning job (202)
GET    /api/plan/{job_id}         – poll job status / result
GET    /api/plan/{job_id}/events  – SSE stream (progress → done/error)
GET    /api/trips                 – list last 20 finished trips (id, destination, dates, created_at)
GET    /api/trips/{trip_id}       – get full trip by id
DELETE /api/trips/{trip_id}       – delete trip by id
GET    /api/share/{slug}          – public read-only trip (excludes origin/request details)
GET    /health                    – liveness probe (never returns secrets)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from app.api.jobs import (
    JobManager,
    JobStore,
    create_sqlite_job_manager,
)
from app.api.schemas import ErrorResponse, JobStatus, PlanRequest
from app.config import get_settings
from app.db import database as db
from app.security import install_secret_masking

logger = logging.getLogger(__name__)

# Install secret masking filter on all root/active loggers
install_secret_masking()

# ── App state – initialized eagerly with SQLite store ─────────────────────────

_store: JobStore
_manager: JobManager

_store, _manager = create_sqlite_job_manager()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize SQLite database and shared state on startup."""
    global _store, _manager
    install_secret_masking()
    db.init_db()
    _store, _manager = create_sqlite_job_manager()
    logger.info("Travel Planner API started (SQLite persistence enabled).")
    yield
    logger.info("Travel Planner API shutting down.")


# ── Limiter instance ─────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ── App instance ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Travel Planner Agent API",
    description="AI-powered trip planning with persistent trips and real-time progress.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security & Request-ID middleware ─────────────────────────────────────────

MAX_BODY_SIZE = 64 * 1024  # 64 KB


@app.middleware("http")
async def _security_and_request_id_middleware(request: Request, call_next):
    # 1. Reject payloads exceeding MAX_BODY_SIZE (64 KB)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds maximum allowed size of 64 KB."},
                )
        except ValueError:
            pass

    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        if len(body) > MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds maximum allowed size of 64 KB."},
            )

    # 2. Assign and log Request ID
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    logger.info(f"[{rid}] {request.method} {request.url.path}")

    # 3. Process request
    response: Response = await call_next(request)

    # 4. Attach security headers and X-Request-ID
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def _generic_exc_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error.").model_dump(),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _job_to_status(job) -> JobStatus:
    return JobStatus(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=job.result,
        error=job.error,
    )


# ── Plan Endpoints ────────────────────────────────────────────────────────────

@app.post(
    "/api/plan",
    status_code=202,
    summary="Submit a trip planning job",
    response_model=dict,
)
@limiter.limit(lambda: f"{get_settings().RATE_LIMIT_PER_MIN}/minute")
async def submit_plan(request: Request, body: PlanRequest):
    """
    Validate the request and enqueue a planning job.
    Returns ``{"job_id": "..."}`` immediately (HTTP 202).
    """
    # Enforce global daily job limit
    settings = get_settings()
    daily_count = db.get_daily_trip_count()
    if daily_count >= settings.DAILY_JOB_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Daily trip limit of {settings.DAILY_JOB_LIMIT} has been reached. Please try again tomorrow.",
        )

    request_dict = {
        "origin": body.origin,
        "destination": body.destination,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "travelers": body.travelers,
        "budget_total": body.budget_total,
        "budget_currency": body.budget_currency,
        "trip_type": body.trip_type,
        "preferences": body.preferences,
        # Pre-populate agent output keys so TripState is complete
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
    job_id = await _manager.submit(request_dict)
    return {"job_id": job_id}


@app.get(
    "/api/plan/{job_id}",
    summary="Poll job status",
    response_model=JobStatus,
)
async def get_plan(job_id: str):
    """Return current status (and result/error when finished)."""
    job = _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return _job_to_status(job)


@app.get(
    "/api/plan/{job_id}/events",
    summary="Server-Sent Events stream for real-time progress",
)
async def plan_events(job_id: str, request: Request):
    """
    SSE stream emitting:
      - ``progress``  (snapshot changed; checked every 400 ms)
      - ``done``      (final result)
      - ``error``     (job failed)
      - heartbeat comment every 15 s
    """
    job = _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    async def _event_generator() -> AsyncIterator[dict]:
        import asyncio
        import time as _time

        last_snap_json: str = ""
        heartbeat_t = 0.0
        poll_interval = 0.4
        heartbeat_interval = 15.0

        while True:
            if await request.is_disconnected():
                break

            current_job = _store.get(job_id)

            # --- Heartbeat comment ---
            now = _time.time()
            if now - heartbeat_t >= heartbeat_interval:
                yield {"comment": "heartbeat"}
                heartbeat_t = now

            # --- Progress snapshot via per-job tracker ---
            tracker = getattr(current_job, "_tracker", None)
            if tracker is not None:
                snap, elapsed = tracker.snapshot()
                snap_json = json.dumps({"stages": snap, "elapsed": elapsed})
                if snap_json != last_snap_json:
                    last_snap_json = snap_json
                    yield {"event": "progress", "data": snap_json}

            # --- Terminal events ---
            if current_job and current_job.status == "done":
                yield {
                    "event": "done",
                    "data": json.dumps({"job_id": job_id, "result": current_job.result}),
                }
                break
            elif current_job and current_job.status == "failed":
                yield {
                    "event": "error",
                    "data": json.dumps({"job_id": job_id, "error": current_job.error}),
                }
                break

            await asyncio.sleep(poll_interval)

    return EventSourceResponse(_event_generator())


# ── Trip Endpoints (Step 2) ───────────────────────────────────────────────────

@app.get(
    "/api/trips",
    summary="List last 20 finished trips",
    response_model=list[dict[str, Any]],
)
async def get_trips(limit: int = 20):
    """Return the last `limit` (default 20) finished trips (id, destination, dates, created_at)."""
    return db.list_trips(limit=limit)


@app.get(
    "/api/trips/{trip_id}",
    summary="Get full trip by id",
    response_model=dict[str, Any],
)
async def get_trip(trip_id: str):
    """Return full trip details by ID."""
    trip = db.get_trip(trip_id)
    if trip is None:
        # Fall back to live store if not yet flushed to DB
        job = _store.get(trip_id)
        if job is not None:
            trip = {
                "id": job.job_id,
                "share_slug": getattr(job, "share_slug", job.job_id),
                "created_at": job.created_at,
                "status": job.status,
                "request": job.request,
                "result": job.result,
                "errors": [job.error] if job.error else [],
                "duration_s": (job.finished_at - job.started_at)
                              if (job.finished_at and job.started_at) else None,
                "timings": None,
                "destination": (job.result or {}).get("destination") or (job.request or {}).get("destination"),
                "dates": f"{(job.request or {}).get('start_date', '')} to {(job.request or {}).get('end_date', '')}".strip(" to "),
            }
        else:
            raise HTTPException(status_code=404, detail=f"Trip '{trip_id}' not found.")
    return trip


@app.delete(
    "/api/trips/{trip_id}",
    summary="Delete a trip by id",
    response_model=dict[str, Any],
)
async def delete_trip(trip_id: str):
    """Delete a trip by ID."""
    success = db.delete_trip(trip_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Trip '{trip_id}' not found.")
    return {"deleted": True, "id": trip_id}


@app.get(
    "/api/share/{slug}",
    summary="Get public read-only trip by share slug",
    response_model=dict[str, Any],
)
async def get_shared_trip(slug: str):
    """
    Public read-only trip view by share slug.
    Excludes request details like origin city for privacy.
    """
    trip = db.get_trip_by_slug(slug)
    if trip is None:
        raise HTTPException(status_code=404, detail="Shared trip not found.")

    # Sanitize: exclude request object and origin city
    result = dict(trip.get("result") or {})
    result.pop("origin", None)

    public_trip = {
        "id": trip["id"],
        "share_slug": trip["share_slug"],
        "created_at": trip["created_at"],
        "status": trip["status"],
        "destination": trip.get("destination"),
        "dates": trip.get("dates"),
        "start_date": trip.get("start_date"),
        "end_date": trip.get("end_date"),
        "duration_s": trip.get("duration_s"),
        "result": result,
        "errors": trip.get("errors") or [],
    }
    return public_trip


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", summary="Liveness probe")
async def health():
    """Returns service health. Never returns secret keys."""
    settings = get_settings()
    has_groq = bool(settings.GROQ_API_KEY.get_secret_value().strip() or os.getenv("GROQ_API_KEY", "").strip())
    has_openrouter = bool(settings.OPENROUTER_API_KEY.get_secret_value().strip() or os.getenv("OPENROUTER_API_KEY", "").strip())
    return {
        "status": "ok",
        "version": app.version,
        "env": settings.ENV,
        "llm_key_configured": has_groq or has_openrouter,
    }


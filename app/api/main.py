"""
FastAPI application for the Travel Planner Agent.

Endpoints
---------
POST  /api/plan                  – submit a new planning job (202)
GET   /api/plan/{job_id}         – poll job status / result
GET   /api/plan/{job_id}/events  – SSE stream (progress → done/error)
GET   /health                    – liveness probe (never returns secrets)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.api.jobs import InMemoryJobStore, JobManager, create_job_manager
from app.api.schemas import ErrorResponse, JobStatus, PlanRequest

logger = logging.getLogger(__name__)

# ── App state – initialized eagerly so tests without lifespan still work ─────

_store: InMemoryJobStore
_manager: JobManager

# Eager initialization (overridden by lifespan on real server startup)
_store, _manager = create_job_manager()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize shared state on startup, clean up on shutdown."""
    global _store, _manager
    _store, _manager = create_job_manager()
    logger.info("Travel Planner API started (lifespan).")
    yield
    logger.info("Travel Planner API shutting down.")


# ── App instance ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Travel Planner Agent API",
    description="AI-powered trip planning with real-time progress streaming.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────

_default_origins = (
    "http://localhost:3000,"
    "http://localhost:5500,"
    "http://127.0.0.1:5500,"
    "http://localhost:8000"
)
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request-ID middleware ─────────────────────────────────────────────────────

@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# ── Global exception handler (no stack traces to clients) ────────────────────

@app.exception_handler(Exception)
async def _generic_exc_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error.").model_dump(),
    )


# ── Helper ───────────────────────────────────────────────────────────────────

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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post(
    "/api/plan",
    status_code=202,
    summary="Submit a trip planning job",
    response_model=dict,
)
async def submit_plan(body: PlanRequest):
    """
    Validate the request and enqueue a planning job.
    Returns ``{"job_id": "..."}`` immediately (HTTP 202).
    """
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
    SSE stream.  Events:
      - ``progress``  (snapshot changed; checked every 400 ms)
      - ``done``      (final result)
      - ``error``     (job failed)
      - heartbeat comment every 15 s (keeps proxies alive)
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


@app.get("/health", summary="Liveness probe")
async def health():
    """
    Returns service health.  LLM key presence is indicated by a boolean –
    the actual key value is NEVER returned.
    """
    groq_configured = bool(os.getenv("GROQ_API_KEY", "").strip())
    return {
        "status": "ok",
        "version": app.version,
        "llm_key_configured": groq_configured,
    }

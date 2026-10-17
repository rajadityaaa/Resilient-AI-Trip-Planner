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
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from app.api.jobs import (
    JobManager,
    JobStore,
    create_sqlite_job_manager,
)
from app.api.schemas import ChatRequest, ChatResponse, ErrorResponse, JobStatus, PlanRequest
from app.config import get_settings
from app.db import database as db
from app.observability.logging import configure_logging, current_request_id
from app.security.sanitize import sanitize_text

logger = logging.getLogger(__name__)

# Configure structured logging (JSON in prod/test, readable in dev) & secret masking
configure_logging()

# ── App state – initialized eagerly with SQLite store ─────────────────────────

_store: JobStore
_manager: JobManager

_store, _manager = create_sqlite_job_manager()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize SQLite database and shared state on startup."""
    global _store, _manager
    configure_logging()
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


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return HTTP 429 with clear JSON error and Retry-After header."""
    return JSONResponse(
        status_code=429,
        content={"error": f"Rate limit exceeded: {exc.detail}"},
        headers={"Retry-After": "60"},
    )

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

    # 2. Assign and log sanitized Request ID (prevents log injection and CRLF header injection)
    raw_rid = request.headers.get("X-Request-ID")
    if raw_rid:
        rid = re.sub(r"[\r\n\x00-\x1f]", "", raw_rid).strip()[:100]
    else:
        rid = str(uuid.uuid4())
    if not rid:
        rid = str(uuid.uuid4())

    rid_token = current_request_id.set(rid)
    try:
        logger.info(f"[{rid}] {request.method} {request.url.path}")

        # 3. Process request
        response: Response = await call_next(request)

        # 4. Attach security headers and X-Request-ID
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 5. Content-Security-Policy header ONLY for static site responses
        path = request.url.path
        if not (path.startswith("/api") or path in ("/docs", "/redoc", "/openapi.json", "/health", "/metrics")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com https://server.arcgisonline.com https://images.unsplash.com; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none';"
            )

        return response
    finally:
        current_request_id.reset(rid_token)


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
    res = job.result
    if res and isinstance(res, dict):
        if not res.get("id"):
            res["id"] = job.job_id
        if not res.get("share_slug") and job.share_slug:
            res["share_slug"] = job.share_slug
    return JobStatus(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=res,
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
                res = dict(current_job.result) if current_job.result else {}
                res["id"] = job_id
                if current_job.share_slug:
                    res["share_slug"] = current_job.share_slug
                yield {
                    "event": "done",
                    "data": json.dumps({"job_id": job_id, "result": res}),
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
    """Return the last `limit` (default 20) finished trips (id, destination, dates, created_at).
    Privacy hardening: Only available when ENV is 'development'.
    """
    if get_settings().ENV != "development":
        raise HTTPException(status_code=404, detail="Not found.")
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


@app.get(
    "/api/share/{slug}/pdf",
    summary="Download itinerary as PDF by share slug",
    response_class=Response,
)
@limiter.limit(lambda: f"{get_settings().RATE_LIMIT_PER_MIN}/minute")
async def download_trip_pdf(request: Request, slug: str):
    """
    Render and download trip itinerary as a PDF using the public share slug only.
    Rate-limited and returns 404 for unknown slugs.
    """
    trip = db.get_trip_by_slug(slug)
    if trip is None:
        raise HTTPException(status_code=404, detail="Shared trip not found.")

    result = trip.get("result") or {}
    try:
        from app.tools.pdf_tools import export_itinerary_pdf
        pdf_bytes = export_itinerary_pdf(result)
    except Exception as exc:
        logger.exception(f"Error generating PDF for trip slug '{slug}': {exc}")
        raise HTTPException(status_code=500, detail="Could not generate PDF.")

    safe_dest = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(trip.get("destination") or "trip"))[:30]
    filename = f"trip_{safe_dest}_{slug[:8]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post(
    "/api/chat",
    summary="Interactive travel assistant chat for planned trips",
    response_model=ChatResponse,
)
@limiter.limit(lambda: f"{get_settings().RATE_LIMIT_PER_MIN}/minute")
async def chat_endpoint(request: Request, body: ChatRequest):
    """
    Provide interactive travel assistant refinement and advice for a saved trip.
    Uses sanitized input, rate limiting, and bounded context.
    """
    trip = db.get_trip(body.trip_id_or_slug) or db.get_trip_by_slug(body.trip_id_or_slug)
    if not trip:
        job = _store.get(body.trip_id_or_slug)
        if job and job.result:
            trip = {"result": job.result}
        elif body.trip_id_or_slug in ("sample-kyoto", "sample"):
            import os
            sample_path = os.path.join(os.path.dirname(__file__), "..", "web", "data", "sample-trip.json")
            if os.path.exists(sample_path):
                try:
                    with open(sample_path, "r", encoding="utf-8") as f:
                        trip = {"result": json.load(f)}
                except Exception as exc:
                    logger.warning(f"Could not load sample trip for chat: {exc}")
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found.")

    user_msg = sanitize_text(body.message.strip())
    if not user_msg:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    clean_context = dict(trip.get("result") or {})
    clean_context.pop("origin", None)  # Privacy
    if "errors" in clean_context:
        clean_context["errors"] = [e.get("message", "") if isinstance(e, dict) else str(e) for e in clean_context["errors"]]

    context_json = json.dumps(clean_context, indent=2, default=str)[:8000]

    system_instruction = (
        "You are an expert AI travel consultant. "
        "The user has planned a trip with the details below. "
        "Help them customize, refine, or answer questions about attractions, restaurants, weather, or pacing. "
        "Be concise, conversational, and helpful. "
        "Only suggest alternative activities from the attractions/restaurants lists already in this trip data. "
        "If none of those fit what the user is asking, say so honestly rather than hallucinating new places.\n\n"
        f"CURRENT TRIP STATE:\n{context_json}"
    )

    try:
        from app.llm.factory import get_llm
        llm = get_llm()
        reply = llm(user_msg, system_instruction=system_instruction)
        return ChatResponse(reply=reply.strip())
    except Exception as exc:
        logger.exception(f"Assistant LLM error: {exc}")
        raise HTTPException(status_code=502, detail="Assistant is temporarily unavailable.")


# ── Stats & Observability ─────────────────────────────────────────────────────

@app.get(
    "/api/stats",
    summary="Platform statistics",
    response_model=dict[str, Any],
)
@limiter.limit(lambda: f"{get_settings().RATE_LIMIT_PER_MIN}/minute")
async def get_stats_endpoint(request: Request):
    """
    Public platform statistics: total trips, success rate, percentiles, agent timings.
    Never exposes personal travel data or user inputs.
    """
    return db.get_stats()


def mount_metrics_route(application: FastAPI) -> None:
    """Mount /metrics endpoint if ENABLE_METRICS is true and not already mounted."""
    from app.config import get_settings
    if not get_settings().ENABLE_METRICS:
        return
    for route in application.routes:
        if getattr(route, "path", None) == "/metrics":
            return

    from starlette.routing import Route

    from app.observability.metrics import get_metrics_content

    async def metrics_endpoint(request: Request = None):
        content, content_type = get_metrics_content()
        return Response(content=content, media_type=content_type)

    route = Route("/metrics", endpoint=metrics_endpoint, methods=["GET"], include_in_schema=False)
    application.router.routes.insert(0, route)


if get_settings().ENABLE_METRICS:
    mount_metrics_route(app)


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


# ── Plan Canonical Redirect ──────────────────────────────────────────────────
@app.get("/plan", include_in_schema=False)
async def plan_redirect():
    """Redirect /plan to canonical /plan/ directory."""
    return RedirectResponse(url="/plan/", status_code=307)


# ── Unknown /api paths return JSON 404 (never index.html) ─────────────────────

@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def api_catchall(path: str):
    return JSONResponse(status_code=404, content={"detail": f"API route '/api/{path}' not found."})


# ── Static Files (HTML5 Web UI) mounted LAST ──────────────────────────────────

_web_dir = Path(__file__).resolve().parent.parent / "web"
if _web_dir.exists():
    app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="static-web")



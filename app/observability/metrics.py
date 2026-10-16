"""
Prometheus metrics for the Travel Planner Agent.
Enabled only when ENABLE_METRICS=true.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Metric instances (initialized lazily or when enabled)
_JOBS_TOTAL = None
_AGENT_DURATION = None
_LLM_FAILURES = None


def _init_metrics():
    global _JOBS_TOTAL, _AGENT_DURATION, _LLM_FAILURES
    if _JOBS_TOTAL is not None:
        return

    try:
        from prometheus_client import Counter, Histogram

        _JOBS_TOTAL = Counter(
            "travel_jobs_total",
            "Total trip planning jobs submitted",
            ["status"],
        )
        _AGENT_DURATION = Histogram(
            "travel_agent_duration_seconds",
            "Agent execution duration in seconds",
            ["agent", "status"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0],
        )
        _LLM_FAILURES = Counter(
            "travel_llm_failures_total",
            "Total LLM call failures by model and error status",
            ["model", "status"],
        )
    except Exception as exc:
        logger.warning(f"[Metrics] Failed to initialize prometheus metrics: {exc}")


def record_job_completed(status: str) -> None:
    _init_metrics()
    if _JOBS_TOTAL is not None:
        try:
            _JOBS_TOTAL.labels(status=status).inc()
        except Exception:
            pass


def record_job_status(status: str) -> None:
    """Alias for record_job_completed."""
    record_job_completed(status)


def record_agent_duration(agent: str, status: str, duration_s: float) -> None:
    _init_metrics()
    if _AGENT_DURATION is not None:
        try:
            _AGENT_DURATION.labels(agent=agent, status=status).observe(max(0.0, float(duration_s)))
        except Exception:
            pass


def record_agent_latency(agent: str, duration_s: float, status: str = "done") -> None:
    """Convenience helper for coordinator latency recording."""
    record_agent_duration(agent, status, duration_s)


def record_llm_failure(model: str, status: str) -> None:
    _init_metrics()
    if _LLM_FAILURES is not None:
        try:
            _LLM_FAILURES.labels(model=str(model or "unknown"), status=str(status or "error")).inc()
        except Exception:
            pass


def get_metrics_content() -> tuple[bytes, str]:
    """Generate Prometheus exposition format data and content type header."""
    _init_metrics()
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(), CONTENT_TYPE_LATEST

"""
LangSmith tracing helper.
Only active when LANGCHAIN_API_KEY is configured and LANGCHAIN_TRACING_V2=true.
Strictly a no-op otherwise with zero network overhead and no import errors.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is enabled via environment variables."""
    api_key = os.getenv("LANGCHAIN_API_KEY", "").strip()
    tracing = os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower()
    return bool(api_key and tracing in ("true", "1", "yes"))


def trace_run(
    name: str,
    run_type: str = "chain",
    inputs: Optional[dict[str, Any]] = None,
    outputs: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """
    Log an event to LangSmith if tracing is enabled.
    Guaranteed no-op when tracing is disabled.
    """
    if not is_tracing_enabled():
        return

    try:
        from langsmith import Client

        client = Client()
        project = os.getenv("LANGCHAIN_PROJECT", "travel-planner-agent")
        client.create_run(
            name=name,
            run_type=run_type,
            inputs=inputs or {},
            outputs=outputs or {},
            error=error,
            project_name=project,
        )
    except Exception as exc:
        logger.debug(f"[Tracing] LangSmith trace failed: {exc}")

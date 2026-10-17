"""
Structured logging module for the Travel Planner Agent.

Features:
- Structured JSON lines for production, staging, and automated tests.
- Human-readable colored/plain format when ENV=development.
- Context-propagated request_id and job_id via ContextVar.
- Automatic secret and key masking via SecretMaskingFilter.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from app.security.logging_filter import SecretMaskingFilter

current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")
current_job_id: ContextVar[str] = ContextVar("current_job_id", default="")


def set_request_id(rid: str) -> None:
    current_request_id.set(rid or "")


def get_request_id() -> str:
    return current_request_id.get("")


def set_job_id(jid: str) -> None:
    current_job_id.set(jid or "")


def get_job_id() -> str:
    return current_job_id.get("")


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": msg,
            "request_id": current_request_id.get(""),
            "job_id": current_job_id.get(""),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class DevelopmentFormatter(logging.Formatter):
    """Readable plaintext formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        rid = current_request_id.get("")
        jid = current_job_id.get("")
        ctx_parts = []
        if rid:
            ctx_parts.append(f"req:{rid}")
        if jid:
            ctx_parts.append(f"job:{jid}")
        ctx = f" [{'|'.join(ctx_parts)}]" if ctx_parts else ""

        dt = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        res = f"{dt} [{record.levelname:<5}] {record.name}{ctx}: {msg}"
        if record.exc_info:
            res += "\n" + self.formatException(record.exc_info)
        return res


_CONFIGURED = False


def configure_logging(env: Optional[str] = None, log_level: Optional[str] = None, force: bool = False) -> None:
    """
    Configure application and root loggers.
    Safe and idempotent: calling multiple times will not duplicate handlers unless force=True.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    _CONFIGURED = True

    try:
        from app.config import get_settings
        settings = get_settings()
        env_val = (env or settings.ENV).lower()
        level_name = (log_level or settings.LOG_LEVEL).upper()
    except Exception:
        env_val = (env or "production").lower()
        level_name = (log_level or "INFO").upper()

    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if env_val == "development":
        handler.setFormatter(DevelopmentFormatter())
    else:
        handler.setFormatter(StructuredJsonFormatter())

    handler.addFilter(SecretMaskingFilter())
    root.addHandler(handler)

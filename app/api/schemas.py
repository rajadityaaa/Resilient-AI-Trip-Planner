"""
Pydantic v2 request/response schemas for the Travel Planner API.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from app.security.sanitize import sanitize_text, sanitize_preferences


TRIP_TYPES = Literal["leisure", "business", "adventure", "family", "solo", "romantic"]


class PlanRequest(BaseModel):
    """Validated input for a trip planning job."""

    origin: str = Field(..., min_length=1, max_length=200, description="Departure city / country.")
    destination: Optional[str] = Field(
        default=None, max_length=200, description="Destination (omit to get AI suggestions)."
    )
    start_date: str = Field(..., description="ISO-8601 date, e.g. 2026-11-10.")
    end_date: str = Field(..., description="ISO-8601 date, e.g. 2026-11-14.")
    travelers: int = Field(..., ge=1, le=20, description="Number of travellers (1-20).")
    budget_total: float = Field(..., gt=0, description="Total trip budget (must be > 0).")
    budget_currency: str = Field(
        ..., min_length=3, max_length=3, description="ISO 4217 currency code, e.g. USD."
    )
    trip_type: TRIP_TYPES = Field(..., description="One of: leisure, business, adventure, family, solo, romantic.")
    preferences: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Up to 10 preference tags, each ≤ 50 chars.",
    )

    # ── validators ──────────────────────────────────────────────────────────

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_iso_date(cls, v: Any) -> str:
        try:
            date.fromisoformat(str(v))
        except (TypeError, ValueError):
            raise ValueError("Must be a valid ISO-8601 date (YYYY-MM-DD).")
        return str(v)

    @field_validator("budget_currency", mode="before")
    @classmethod
    def _validate_currency(cls, v: Any) -> str:
        s = str(v).strip()
        if not re.fullmatch(r"[A-Z]{3}", s):
            raise ValueError("budget_currency must be exactly 3 uppercase letters (ISO 4217).")
        return s

    @field_validator("origin", mode="before")
    @classmethod
    def _sanitize_origin(cls, v: Any) -> str:
        cleaned = sanitize_text(str(v), max_length=200)
        if not cleaned:
            raise ValueError("origin must not be empty.")
        return cleaned

    @field_validator("destination", mode="before")
    @classmethod
    def _sanitize_destination(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        cleaned = sanitize_text(str(v), max_length=200)
        return cleaned if cleaned else None

    @field_validator("preferences", mode="before")
    @classmethod
    def _validate_preferences(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("preferences must be a list.")
        if len(v) > 10:
            raise ValueError("preferences may contain at most 10 items.")
        for item in v:
            if not isinstance(item, str):
                raise ValueError("Each preference must be a string.")
            if len(item) > 50:
                raise ValueError(f"Preference '{item[:20]}…' exceeds 50 characters.")
        return sanitize_preferences(v, max_items=10, max_item_len=50)

    @model_validator(mode="after")
    def _validate_date_range(self) -> "PlanRequest":
        try:
            s = date.fromisoformat(self.start_date)
            e = date.fromisoformat(self.end_date)
        except ValueError:
            return self  # already caught above
        if e < s:
            raise ValueError("end_date must be on or after start_date.")
        if (e - s).days > 21:
            raise ValueError("Trip length must not exceed 21 days.")
        return self


# ── Response models ──────────────────────────────────────────────────────────

class JobStatus(BaseModel):
    """Minimal job status payload."""

    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class PlanResult(BaseModel):
    """Full plan result returned when a job is done."""

    job_id: str
    status: str
    result: dict[str, Any]


class ErrorResponse(BaseModel):
    """Consistent JSON error envelope."""

    detail: str
    request_id: Optional[str] = None

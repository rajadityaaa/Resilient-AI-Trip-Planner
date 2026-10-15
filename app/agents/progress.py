"""
Thread-safe progress tracker.

Architecture (Step 1 refactor):
- ``ProgressTracker``  – a self-contained, per-job tracker instance.
- ``current_tracker``  – a ``contextvars.ContextVar`` pointing to the active tracker
                         for the current async task / worker thread.
- Module-level ``reset``, ``set_status``, ``snapshot`` functions delegate to the
  tracker resolved from ``current_tracker`` (falling back to ``_default_tracker``).
  This keeps the existing Streamlit path fully working.

How it wires together:
  plan_trip() creates / receives a ProgressTracker, sets current_tracker,
  then runs the LangGraph graph.  Agents call module-level set_status() which
  reads current_tracker and therefore writes to the right per-job tracker.
  asyncio.to_thread() propagates the contextvars context automatically.
"""
from __future__ import annotations

import contextvars
import threading
import time
from typing import Optional

# ── Stage registry ──────────────────────────────────────────────────────────

STAGES = [
    ("destination", "📍 Destination & location"),
    ("weather", "🌦️ Weather forecast"),
    ("attractions", "🏰 Attractions (OpenStreetMap)"),
    ("restaurants", "🍜 Restaurants & local food"),
    ("hotels", "🏨 Hotels"),
    ("budget_breakdown", "💰 Budget split"),
    ("transport_guide", "🚗 Local transport"),
    ("packing_list", "🎒 Packing list"),
    ("currency_info", "💱 Currency & cash tips"),
    ("summary", "📝 Day-by-day itinerary"),
]


# ── ProgressTracker class ────────────────────────────────────────────────────

class ProgressTracker:
    """
    Self-contained, per-job progress tracker.

    Methods mirror the old module-level API so they are drop-in replaceable.
    All public methods are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict = {}
        self._started_at: float = 0.0
        self.reset()

    def reset(self) -> None:
        """Reinitialise all stages to pending."""
        with self._lock:
            self._status = {key: {"status": "pending", "detail": "", "t": 0.0} for key, _ in STAGES}
            self._started_at = time.time()

    def set_status(self, key: str, status: str, detail: str = "") -> None:
        """
        Update a stage.

        :param key: Stage key (e.g. ``"weather"``).
        :param status: ``pending`` | ``running`` | ``done`` | ``warn`` | ``failed``
        :param detail: Short human-readable detail string.
        """
        with self._lock:
            entry = self._status.setdefault(key, {"status": "pending", "detail": "", "t": 0.0})
            entry["status"] = status
            entry["detail"] = detail
            entry["t"] = time.time() - self._started_at

    def snapshot(self) -> tuple[dict, float]:
        """Return a deep copy of the current status plus elapsed seconds."""
        with self._lock:
            return (
                {k: dict(v) for k, v in self._status.items()},
                (time.time() - self._started_at if self._started_at else 0.0),
            )


# ── ContextVar ───────────────────────────────────────────────────────────────

_default_tracker = ProgressTracker()

current_tracker: contextvars.ContextVar[ProgressTracker] = contextvars.ContextVar(
    "current_tracker", default=_default_tracker
)


def _active() -> ProgressTracker:
    """Return the tracker bound to the current async context (or the default)."""
    return current_tracker.get()


# ── Module-level API (backward-compatible for Streamlit & old code) ──────────

def reset() -> None:
    """Reset the active tracker for this context."""
    _active().reset()


def set_status(key: str, status: str, detail: str = "") -> None:
    """Update a stage on the active tracker for this context."""
    _active().set_status(key, status, detail)


def snapshot() -> tuple[dict, float]:
    """Return a snapshot of the active tracker for this context."""
    return _active().snapshot()

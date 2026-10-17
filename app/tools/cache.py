"""
Cache layer: SQLite-backed with automatic in-memory fallback.

Public API (identical to the original):
    cache_get(key)                  -> Optional[Any]
    cache_set(key, value, ttl=3600) -> None
    cache_clear()                   -> None

Internals:
- Values are JSON-serialised before storage and deserialised on retrieval.
- If the SQLite DB is unavailable for any reason, falls back to the in-memory
  dict silently without raising exceptions to callers.
- Expired rows are purged opportunistically: ~1 in every 50 cache_set() calls
  triggers a purge of expired rows in SQLite.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── In-memory fallback (used when SQLite is unavailable) ─────────────────────
# key -> (value, expiry_timestamp)
_FALLBACK: dict[str, tuple[Any, float]] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def cache_get(key: str) -> Optional[Any]:
    """
    Retrieve a value from cache if it exists and has not expired.

    Args:
        key: Unique cache key string.

    Returns:
        The cached value if present and valid, otherwise None.
    """
    try:
        from app.db import database as db
        raw = db.cache_get_raw(key)
        if raw is not None:
            return json.loads(raw)
        # Check fallback if not in DB (e.g. set during a previous DB failure)
        return _fallback_get(key)
    except Exception as exc:
        logger.debug(f"[Cache] SQLite get error, falling back to memory: {exc}")
        return _fallback_get(key)


def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """
    Store a value in cache with a given TTL.

    Args:
        key:         Unique cache key string.
        value:       Any JSON-serialisable Python object.
        ttl_seconds: Time-to-live in seconds (default: 3600 / 1 hour).
    """
    expires_at = time.time() + ttl_seconds
    try:
        from app.db import database as db
        raw = json.dumps(value)
        db.cache_set_raw(key, raw, expires_at)
        # Opportunistic purge (~1 in 50 writes)
        if random.randint(1, 50) == 1:
            try:
                db.cache_purge_expired()
            except Exception:
                pass
    except Exception as exc:
        logger.debug(f"[Cache] SQLite set error, falling back to memory: {exc}")
        _fallback_set(key, value, expires_at)


def cache_clear() -> None:
    """Clear all cached entries (both SQLite and in-memory fallback)."""
    _FALLBACK.clear()
    try:
        from app.db import database as db
        db.cache_clear_all()
    except Exception as exc:
        logger.debug(f"[Cache] SQLite clear error: {exc}")


# ── Fallback helpers ──────────────────────────────────────────────────────────

def _fallback_get(key: str) -> Optional[Any]:
    if key not in _FALLBACK:
        return None
    value, expiry = _FALLBACK[key]
    if time.time() > expiry:
        del _FALLBACK[key]
        return None
    return value


def _fallback_set(key: str, value: Any, expires_at: float) -> None:
    _FALLBACK[key] = (value, expires_at)

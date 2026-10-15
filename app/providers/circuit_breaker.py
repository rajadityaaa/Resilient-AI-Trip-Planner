"""
Circuit breaker for external providers and data sources.
Persists state via SQLite-backed cache (app.tools.cache).

Rules:
- 3 consecutive failures trips the breaker.
- When tripped, the provider is disabled for 5 minutes (CIRCUIT_COOLDOWN_S = 300).
- When all Overpass mirrors fail, the breaker can be tripped immediately for 5 minutes.
"""
from __future__ import annotations

import logging
import time

from app.tools.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

CIRCUIT_COOLDOWN_S = 300  # 5 minutes
FAILURE_THRESHOLD = 3     # 3 consecutive failures


def is_circuit_open(name: str) -> bool:
    """
    Check if the circuit is OPEN (disabled/tripped) for `name`.
    Returns True if calls to this provider should be skipped immediately.
    """
    open_until = cache_get(f"circuit_breaker:{name}:open_until")
    if open_until is not None:
        try:
            if float(open_until) > time.time():
                return True
        except (ValueError, TypeError):
            pass
    return False


def record_success(name: str) -> None:
    """Record a successful call. Resets consecutive failure counter and closes circuit."""
    cache_set(f"circuit_breaker:{name}:failures", 0, ttl_seconds=3600)
    cache_set(f"circuit_breaker:{name}:open_until", 0.0, ttl_seconds=1)


def record_failure(name: str, force_trip: bool = False, cooldown_s: int = CIRCUIT_COOLDOWN_S) -> bool:
    """
    Record a failed call.
    If force_trip is True or consecutive failures reach FAILURE_THRESHOLD,
    trips the circuit for `cooldown_s` (default 5 minutes).

    Returns True if the circuit is now OPEN.
    """
    if force_trip:
        trip_circuit(name, cooldown_s=cooldown_s)
        return True

    current_failures = cache_get(f"circuit_breaker:{name}:failures")
    try:
        failures = int(current_failures) + 1 if current_failures is not None else 1
    except (ValueError, TypeError):
        failures = 1

    if failures >= FAILURE_THRESHOLD:
        trip_circuit(name, cooldown_s=cooldown_s)
        return True
    else:
        cache_set(f"circuit_breaker:{name}:failures", failures, ttl_seconds=3600)
        return False


def trip_circuit(name: str, cooldown_s: int = CIRCUIT_COOLDOWN_S) -> None:
    """Explicitly trip the circuit breaker for `name` for `cooldown_s` seconds."""
    now = time.time()
    cache_set(f"circuit_breaker:{name}:open_until", now + cooldown_s, ttl_seconds=cooldown_s)
    cache_set(f"circuit_breaker:{name}:failures", FAILURE_THRESHOLD, ttl_seconds=cooldown_s)
    logger.warning(f"[CircuitBreaker] Circuit for '{name}' is OPEN for {cooldown_s}s.")


def reset_circuit(name: str) -> None:
    """Completely reset the circuit breaker for `name` (for tests)."""
    record_success(name)

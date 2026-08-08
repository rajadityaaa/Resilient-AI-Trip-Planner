import time
from typing import Any, Optional

# In-memory dictionary storing: key -> (value, expiry_timestamp)
_CACHE: dict[str, tuple[Any, float]] = {}


def cache_get(key: str) -> Optional[Any]:
    """
    Retrieve value from in-memory cache if it exists and has not expired.

    Args:
        key: Unique cache key string.

    Returns:
        The cached value if present and valid, otherwise None.
    """
    if key not in _CACHE:
        return None

    value, expiry = _CACHE[key]
    if time.time() > expiry:
        del _CACHE[key]
        return None

    return value


def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """
    Store a value in in-memory cache with a given TTL in seconds.

    Args:
        key: Unique cache key string.
        value: Any Python object to cache.
        ttl_seconds: Time-To-Live duration in seconds (default: 3600 seconds / 1 hour).
    """
    expiry = time.time() + ttl_seconds
    _CACHE[key] = (value, expiry)


def cache_clear() -> None:
    """Clear all cached entries."""
    _CACHE.clear()

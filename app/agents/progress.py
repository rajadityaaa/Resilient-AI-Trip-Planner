"""
Thread-safe progress tracker. Agents (running in worker threads) write their status here;
the Streamlit UI (main thread) reads a snapshot every few hundred ms and renders a live checklist.
"""
import threading
import time

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

_lock = threading.Lock()
_status: dict = {}
_started_at: float = 0.0


def reset() -> None:
    global _started_at
    with _lock:
        _status.clear()
        for key, _ in STAGES:
            _status[key] = {"status": "pending", "detail": "", "t": 0.0}
        _started_at = time.time()


def set_status(key: str, status: str, detail: str = "") -> None:
    """status: pending | running | done | warn | failed"""
    with _lock:
        entry = _status.setdefault(key, {"status": "pending", "detail": "", "t": 0.0})
        entry["status"] = status
        entry["detail"] = detail
        entry["t"] = time.time() - _started_at


def snapshot() -> tuple[dict, float]:
    with _lock:
        return {k: dict(v) for k, v in _status.items()}, (time.time() - _started_at if _started_at else 0.0)

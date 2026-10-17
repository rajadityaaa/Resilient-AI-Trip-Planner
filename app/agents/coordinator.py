"""
Coordinator Agent: Orchestrates the multi-agent workflow using LangGraph.

Pipeline (parallelised for speed):
  START -> destination_node            (resolve/suggest + warm geocode cache)
        -> parallel_node               (weather->packing, attractions, restaurants, hotels,
                                        budget, transport, currency — all run concurrently)
        -> summary_node -> END         (needs everything above, so it runs last)

Each agent runs in its own worker thread with a hard timeout, so one slow API can
no longer stall the whole run. summary_node ALWAYS runs, even if agents logged errors.
"""
import asyncio
import time
from contextvars import ContextVar
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from app.agents import progress
from app.agents.attraction_agent import get_attractions_for_trip
from app.agents.budget_agent import build_budget
from app.agents.currency_agent import build_currency_info
from app.agents.destination_agent import suggest_destinations
from app.agents.hotel_agent import get_hotels
from app.agents.packing_agent import build_packing_list
from app.agents.progress import ProgressTracker, current_tracker
from app.agents.restaurant_agent import get_restaurants_for_trip
from app.agents.state import TripState
from app.agents.summary_agent import build_summary
from app.agents.transport_agent import build_transport_guide
from app.agents.weather_agent import get_weather

# ── Parallel execution helpers ──────────────────────────────────────────────
# The agents are `async def` but internally use blocking `requests` / sleep calls,
# so asyncio.gather alone would NOT overlap them. We run each agent in its own worker
# thread (with its own event loop) so network + LLM waits genuinely overlap.
from app.config import get_settings
from app.tools.geocode_tools import geocode_place

current_timings_collector: ContextVar[Optional[dict]] = ContextVar("current_timings_collector", default=None)

AGENT_TIMEOUT_S = get_settings().AGENT_TIMEOUT_S          # hard cap per agent so one slow API can't stall the whole run
_OUTPUT_KEYS = {
    "weather": get_weather,
    "attractions": get_attractions_for_trip,
    "restaurants": get_restaurants_for_trip,
    "hotels": get_hotels,
    "budget_breakdown": build_budget,
    "transport_guide": build_transport_guide,
    "currency_info": build_currency_info,
}


def _run_agent_sync(agent_fn, state_copy: dict) -> tuple[dict, Optional[str]]:
    from app.llm.factory import last_llm_model
    last_llm_model.set(None)
    res = asyncio.run(agent_fn(state_copy))
    return res, last_llm_model.get()


def _describe(result: dict, key: str) -> tuple[str, str]:
    """Return (status, detail) for a finished agent based on its output."""
    val = result.get(key)
    errs = [e for e in result.get("errors", []) if e.get("agent", "").startswith(key.split("_")[0][:6])]
    if val in (None, [], {}):
        return "warn", "no data (fallback used)"
    if isinstance(val, list):
        detail = f"{len(val)} found"
    elif isinstance(val, dict) and "daily" in val:
        detail = f"{len(val['daily'])} days" + (" (climate estimate)" if val.get("is_estimate") else "")
    else:
        detail = "ready"
    return ("warn" if errs else "done"), detail


def _inspect_agent_source_and_fallback(name: str, result: dict, status: str) -> tuple[Optional[str], bool]:
    """Determine data source and whether fallback/estimated data was used."""
    fallback_used = (status in ("warn", "failed", "timeout"))
    source = None

    val = result.get(name)
    errs = [e for e in result.get("errors", []) if e.get("agent", "").startswith(name.split("_")[0][:6])]
    if errs:
        fallback_used = True

    if name == "attractions" and isinstance(val, list) and val:
        source = val[0].get("source")
        if any(item.get("source") in ("ai", "ai_suggested", "fallback") for item in val):
            fallback_used = True
    elif name == "restaurants" and isinstance(val, list) and val:
        source = val[0].get("source")
        if any(item.get("source") in ("ai", "ai_suggested", "fallback") for item in val):
            fallback_used = True
    elif name == "hotels" and isinstance(val, list) and val:
        source = val[0].get("source")
        if any(item.get("source") in ("ai", "ai_suggested", "fallback") or item.get("price_source") == "estimated" for item in val):
            fallback_used = True
    elif name == "weather":
        if isinstance(val, dict):
            if val.get("is_estimate"):
                source = "estimate"
                fallback_used = True
            else:
                source = "open-meteo"
    elif name == "currency_info":
        if isinstance(val, dict):
            source = val.get("rates_source") or "open.er-api.com"
            if val.get("is_estimate") or source == "fallback":
                fallback_used = True
    elif name == "packing_list":
        if result.get("packing_list") is None or not result.get("packing_list"):
            fallback_used = True

    return source, fallback_used


def _record_timing(
    name: str,
    start_offset_s: float,
    duration_s: float,
    status: str,
    fallback_used: bool,
    source: Optional[str],
    llm_model: Optional[str],
) -> None:
    collector = current_timings_collector.get(None)
    if collector is not None:
        collector["agents"][name] = {
            "name": name,
            "start_offset_s": start_offset_s,
            "duration_s": duration_s,
            "status": status,
            "fallback_used": fallback_used,
            "source": source,
            "llm_model": llm_model,
        }
    try:
        from app.observability.metrics import record_agent_latency
        record_agent_latency(name, duration_s)
    except Exception:
        pass


def _compute_critical_path(agents: dict[str, dict]) -> list[str]:
    """Calculate the slowest agent chain (critical path)."""
    branches = [
        (["weather", "packing_list"], agents.get("weather", {}).get("duration_s", 0.0) + agents.get("packing_list", {}).get("duration_s", 0.0)),
        (["attractions"], agents.get("attractions", {}).get("duration_s", 0.0)),
        (["restaurants"], agents.get("restaurants", {}).get("duration_s", 0.0)),
        (["hotels"], agents.get("hotels", {}).get("duration_s", 0.0)),
        (["budget_breakdown"], agents.get("budget_breakdown", {}).get("duration_s", 0.0)),
        (["transport_guide"], agents.get("transport_guide", {}).get("duration_s", 0.0)),
        (["currency_info"], agents.get("currency_info", {}).get("duration_s", 0.0)),
    ]
    slowest_branch, _ = max(branches, key=lambda item: item[1])
    path = []
    if "destination" in agents:
        path.append("destination")
    path.extend([a for a in slowest_branch if a in agents])
    if "summary" in agents:
        path.append("summary")
    return path


async def _run_agent_threaded(name: str, agent_fn, state: dict) -> tuple[str, dict]:
    """Run one agent on a copy of the state in a worker thread; never raises."""
    local = dict(state)
    local["errors"] = []
    progress.set_status(name, "running")

    collector = current_timings_collector.get(None)
    job_start = collector["start_time"] if collector else time.perf_counter()
    start_offset_s = round(time.perf_counter() - job_start, 3)
    t0 = time.perf_counter()

    try:
        result, llm_model = await asyncio.wait_for(
            asyncio.to_thread(_run_agent_sync, agent_fn, local), timeout=AGENT_TIMEOUT_S
        )
        duration_s = round(time.perf_counter() - t0, 3)
        status, detail = _describe(result, name)
        source, fallback_used = _inspect_agent_source_and_fallback(name, result, status)
        progress.set_status(name, status, detail)
        _record_timing(name, start_offset_s, duration_s, status, fallback_used, source, llm_model)
        return name, result
    except Exception as err:  # includes TimeoutError
        duration_s = round(time.perf_counter() - t0, 3)
        status = "timeout" if isinstance(err, asyncio.TimeoutError) else "failed"
        local["errors"].append({"agent": name, "message": f"{name}: {type(err).__name__} {err}".strip()})
        detail = "timed out - using fallback" if status == "timeout" else "failed - using fallback"
        progress.set_status(name, "failed", detail)
        _record_timing(name, start_offset_s, duration_s, status, fallback_used=True, source=None, llm_model=None)
        return name, local


def _resolve_destination(state: dict):
    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions") or []
        if suggs:
            dest = suggs[0].get("destination")
    return dest


# ── Graph nodes ─────────────────────────────────────────────────────────────

async def destination_node(state: dict) -> dict:
    progress.set_status("destination", "running")
    collector = current_timings_collector.get(None)
    job_start = collector["start_time"] if collector else time.perf_counter()
    start_offset_s = round(time.perf_counter() - job_start, 3)
    t0 = time.perf_counter()
    status = "done"
    fallback_used = False
    source = None
    llm_model = None

    try:
        state, llm_model = await asyncio.to_thread(_run_agent_sync, suggest_destinations, state)
        dest = _resolve_destination(state)
        if dest:
            try:
                await asyncio.to_thread(geocode_place, dest)
            except Exception:
                pass
        progress.set_status("destination", "done", str(dest) if dest else "no destination")
    except Exception as err:
        status = "failed"
        fallback_used = True
        state.setdefault("errors", []).append({"agent": "destination", "message": f"destination: {type(err).__name__} {err}".strip()})
        progress.set_status("destination", "failed", "failed - using fallback")

    duration_s = round(time.perf_counter() - t0, 3)
    _record_timing("destination", start_offset_s, duration_s, status, fallback_used, source, llm_model)
    return state


async def parallel_node(state: dict) -> dict:
    """
    Fan out all independent agents at once.
    weather -> packing is chained (packing needs the weather summary); everything else is independent.
    """
    async def weather_then_packing():
        n, w_state = await _run_agent_threaded("weather", get_weather, state)
        p_input = dict(state)
        p_input["weather"] = w_state.get("weather")
        _, p_state = await _run_agent_threaded("packing_list", build_packing_list, p_input)
        # merge errors from both
        p_state["errors"] = list(w_state.get("errors", [])) + list(p_state.get("errors", []))
        p_state["weather"] = w_state.get("weather")
        return [("weather", p_state), ("packing_list", p_state)]

    async def single(name, fn):
        return [await _run_agent_threaded(name, fn, state)]

    jobs = [weather_then_packing()] + [
        single(n, f) for n, f in _OUTPUT_KEYS.items() if n != "weather"
    ]
    groups = await asyncio.gather(*jobs)

    seen_error_ids = set()
    for group in groups:
        for key, res in group:
            if key in res:
                state[key] = res[key]
            for e in res.get("errors", []):
                eid = (e.get("agent"), e.get("message"))
                if eid not in seen_error_ids:
                    seen_error_ids.add(eid)
                    state["errors"].append(e)
    return state


async def summary_node(state: dict) -> dict:
    progress.set_status("summary", "running")
    collector = current_timings_collector.get(None)
    job_start = collector["start_time"] if collector else time.perf_counter()
    start_offset_s = round(time.perf_counter() - job_start, 3)
    t0 = time.perf_counter()
    status = "done"
    fallback_used = False
    source = None
    llm_model = None

    try:
        from app.llm.factory import last_llm_model
        last_llm_model.set(None)
        res = await build_summary(state)
        llm_model = last_llm_model.get()
        if res.get("itinerary_is_fallback") or any(e.get("agent") == "summary" for e in res.get("errors", [])):
            fallback_used = True
            status = "warn"
        progress.set_status("summary", status, "complete")
    except Exception as err:
        status = "failed"
        fallback_used = True
        res = state
        res.setdefault("errors", []).append({"agent": "summary", "message": f"summary: {type(err).__name__} {err}".strip()})
        progress.set_status("summary", "failed", "failed")

    duration_s = round(time.perf_counter() - t0, 3)
    _record_timing("summary", start_offset_s, duration_s, status, fallback_used, source, llm_model)
    return res


# ── Graph Construction ──────────────────────────────────────────────────────

def build_coordinator_graph() -> StateGraph:
    """
    START -> destination_node -> parallel_node (weather+packing, attractions, restaurants,
             hotels, budget, transport, currency — all concurrent) -> summary_node -> END
    """
    graph = StateGraph(dict)
    graph.add_node("destination_node", destination_node)
    graph.add_node("parallel_node", parallel_node)
    graph.add_node("summary_node", summary_node)

    graph.add_edge(START, "destination_node")
    graph.add_edge("destination_node", "parallel_node")
    graph.add_edge("parallel_node", "summary_node")
    graph.add_edge("summary_node", END)
    return graph


# ── Public API ──────────────────────────────────────────────────────────────

async def plan_trip(
    initial_state: TripState,
    progress_tracker: Optional[ProgressTracker] = None,
) -> TripState:
    """
    Run the full trip planner pipeline.

    Args:
        initial_state:     A TripState dict with user inputs populated.
        progress_tracker:  Optional per-job ProgressTracker.  When provided,
                           it is bound to the ``current_tracker`` ContextVar so
                           all agents in this call (including those running in
                           worker threads via asyncio.to_thread, which copies
                           the context) automatically write to this tracker.
                           When omitted, the module-level default tracker is used
                           (Streamlit path).

    Returns:
        TripState: The completed state dict with all agent outputs populated,
                   including state["errors"] (empty list = fully successful run).
    """
    # Ensure errors list is initialized
    if "errors" not in initial_state or initial_state["errors"] is None:
        initial_state["errors"] = []

    # Defense-in-depth: sanitize user inputs at pipeline entry
    from app.security.sanitize import sanitize_preferences, sanitize_text
    if initial_state.get("preferences"):
        initial_state["preferences"] = sanitize_preferences(initial_state["preferences"])
    if initial_state.get("origin"):
        initial_state["origin"] = sanitize_text(initial_state["origin"], max_length=100)
    if initial_state.get("destination"):
        initial_state["destination"] = sanitize_text(initial_state["destination"], max_length=100)

    # Bind the tracker to the current async context.
    # asyncio.to_thread() copies the context, so worker threads see the same tracker.
    if progress_tracker is not None:
        token = current_tracker.set(progress_tracker)
    else:
        token = None

    timings_data: dict[str, Any] = {
        "start_time": time.perf_counter(),
        "agents": {},
    }
    timings_token = current_timings_collector.set(timings_data)

    try:
        progress.reset()  # resets whichever tracker is active for this context

        graph = build_coordinator_graph()
        compiled = graph.compile()

        # LangGraph async invoke returns the final state
        final_state = await compiled.ainvoke(initial_state)
    except Exception:
        total_duration_s = round(time.perf_counter() - timings_data["start_time"], 3)
        initial_state["timings"] = {
            "total_duration_s": total_duration_s,
            "critical_path": _compute_critical_path(timings_data["agents"]),
            "agents": timings_data["agents"],
        }
        raise
    finally:
        current_timings_collector.reset(timings_token)
        if token is not None:
            current_tracker.reset(token)

    total_duration_s = round(time.perf_counter() - timings_data["start_time"], 3)
    critical_path = _compute_critical_path(timings_data["agents"])
    final_state["timings"] = {
        "total_duration_s": total_duration_s,
        "critical_path": critical_path,
        "agents": timings_data["agents"],
    }

    try:
        from app.observability.tracing import trace_run
        trace_run(
            "plan_trip",
            inputs={"destination": final_state.get("destination") or initial_state.get("destination")},
            outputs={"status": "warn" if final_state.get("errors") else "done", "duration_s": total_duration_s},
        )
    except Exception:
        pass

    return final_state

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
from langgraph.graph import StateGraph, START, END

from app.agents.state import TripState
from app.agents.destination_agent import suggest_destinations
from app.agents.weather_agent import get_weather
from app.agents.attraction_agent import get_attractions_for_trip
from app.agents.restaurant_agent import get_restaurants_for_trip
from app.agents.hotel_agent import get_hotels
from app.agents.budget_agent import build_budget
from app.agents.transport_agent import build_transport_guide
from app.agents.packing_agent import build_packing_list
from app.agents.currency_agent import build_currency_info
from app.agents.summary_agent import build_summary
from app.tools.geocode_tools import geocode_place
from app.agents import progress


# ── Parallel execution helpers ──────────────────────────────────────────────
# The agents are `async def` but internally use blocking `requests` / sleep calls,
# so asyncio.gather alone would NOT overlap them. We run each agent in its own worker
# thread (with its own event loop) so network + LLM waits genuinely overlap.

AGENT_TIMEOUT_S = 48          # hard cap per agent so one slow API can't stall the whole run
_OUTPUT_KEYS = {
    "weather": get_weather,
    "attractions": get_attractions_for_trip,
    "restaurants": get_restaurants_for_trip,
    "hotels": get_hotels,
    "budget_breakdown": build_budget,
    "transport_guide": build_transport_guide,
    "currency_info": build_currency_info,
}


def _run_agent_sync(agent_fn, state_copy: dict) -> dict:
    return asyncio.run(agent_fn(state_copy))


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


async def _run_agent_threaded(name: str, agent_fn, state: dict) -> tuple[str, dict]:
    """Run one agent on a copy of the state in a worker thread; never raises."""
    local = dict(state)
    local["errors"] = []
    progress.set_status(name, "running")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_agent_sync, agent_fn, local), timeout=AGENT_TIMEOUT_S
        )
        status, detail = _describe(result, name)
        progress.set_status(name, status, detail)
        return name, result
    except Exception as err:  # includes TimeoutError
        local["errors"].append({"agent": name, "message": f"{name}: {type(err).__name__} {err}".strip()})
        progress.set_status(name, "failed", "timed out - using fallback" if isinstance(err, asyncio.TimeoutError) else "failed - using fallback")
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
    state = await asyncio.to_thread(lambda: asyncio.run(suggest_destinations(state)))
    # Warm the geocode cache ONCE here. Every parallel agent below re-geocodes the same
    # place; without this they'd all race Nominatim's 1 req/sec limit.
    dest = _resolve_destination(state)
    if dest:
        try:
            await asyncio.to_thread(geocode_place, dest)
        except Exception:
            pass
    progress.set_status("destination", "done", str(dest) if dest else "no destination")
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
    return await build_summary(state)


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

async def plan_trip(initial_state: TripState) -> TripState:
    """
    Run the full trip planner pipeline.

    Args:
        initial_state: A TripState dict with user inputs populated.

    Returns:
        TripState: The completed state dict with all agent outputs populated,
                   including state["errors"] (empty list = fully successful run).
    """
    # Ensure errors list is initialized
    if "errors" not in initial_state or initial_state["errors"] is None:
        initial_state["errors"] = []
    progress.reset()

    graph = build_coordinator_graph()
    compiled = graph.compile()

    # LangGraph async invoke returns the final state
    final_state = await compiled.ainvoke(initial_state)

    return final_state

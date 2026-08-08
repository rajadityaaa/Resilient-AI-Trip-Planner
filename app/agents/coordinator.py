"""
Coordinator Agent: Orchestrates the multi-agent execution workflow using LangGraph StateGraph.

Pipeline (mostly linear):
  START -> destination_node -> weather_node -> attraction_node -> restaurant_node -> hotel_node
       -> budget_node -> transport_node -> packing_node -> currency_node -> summary_node -> END

NOTE: weather_node, attraction_node, restaurant_node, and hotel_node all depend on having a
resolved destination (from destination_node) but are otherwise independent of each other.
They are candidates for parallelization using asyncio.gather in a FastAPI deployment.
For LangGraph MVP simplicity, they run sequentially.

summary_node ALWAYS runs last, even if upstream agents logged errors.
"""
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


# ── Natively Async Node Wrapper Functions ──────────────────────────────────
# In LangGraph, async nodes are natively supported. When the graph is invoked
# asynchronously via `ainvoke`, the execution engine executes them concurrently
# or sequentially as required within the existing asyncio event loop.

async def destination_node(state: dict) -> dict:
    return await suggest_destinations(state)


async def weather_node(state: dict) -> dict:
    return await get_weather(state)


async def attraction_node(state: dict) -> dict:
    return await get_attractions_for_trip(state)


async def restaurant_node(state: dict) -> dict:
    return await get_restaurants_for_trip(state)


async def hotel_node(state: dict) -> dict:
    return await get_hotels(state)


async def budget_node(state: dict) -> dict:
    return await build_budget(state)


async def transport_node(state: dict) -> dict:
    return await build_transport_guide(state)


async def packing_node(state: dict) -> dict:
    return await build_packing_list(state)


async def currency_node(state: dict) -> dict:
    return await build_currency_info(state)


async def summary_node(state: dict) -> dict:
    return await build_summary(state)


# ── Graph Construction ──────────────────────────────────────────────────────

def build_coordinator_graph() -> StateGraph:
    """
    Construct the LangGraph workflow graph.

    Pipeline:
      START -> destination_node -> weather_node -> attraction_node -> restaurant_node
            -> hotel_node -> budget_node -> transport_node -> packing_node
            -> currency_node -> summary_node -> END
    """
    graph = StateGraph(dict)

    # Add all 10 nodes
    graph.add_node("destination_node", destination_node)
    graph.add_node("weather_node", weather_node)
    graph.add_node("attraction_node", attraction_node)
    graph.add_node("restaurant_node", restaurant_node)
    graph.add_node("hotel_node", hotel_node)
    graph.add_node("budget_node", budget_node)
    graph.add_node("transport_node", transport_node)
    graph.add_node("packing_node", packing_node)
    graph.add_node("currency_node", currency_node)
    graph.add_node("summary_node", summary_node)

    # Wire edges — linear sequential pipeline
    graph.add_edge(START, "destination_node")
    graph.add_edge("destination_node", "weather_node")

    # NOTE: weather, attraction, restaurant, hotel all depend only on destination being resolved.
    # They are independent of each other and could be parallelized with asyncio.gather
    # in a FastAPI deployment. Kept sequential for LangGraph MVP simplicity.
    graph.add_edge("weather_node", "attraction_node")
    graph.add_edge("attraction_node", "restaurant_node")
    graph.add_edge("restaurant_node", "hotel_node")

    # Budget depends on hotel + restaurant price data already being in state
    graph.add_edge("hotel_node", "budget_node")

    graph.add_edge("budget_node", "transport_node")
    graph.add_edge("transport_node", "packing_node")
    graph.add_edge("packing_node", "currency_node")
    graph.add_edge("currency_node", "summary_node")
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

    graph = build_coordinator_graph()
    compiled = graph.compile()

    # LangGraph async invoke returns the final state
    final_state = await compiled.ainvoke(initial_state)

    return final_state

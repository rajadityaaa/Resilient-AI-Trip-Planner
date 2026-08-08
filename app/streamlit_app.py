import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Streamlit Web Application: Main entry point for the AI Travel Planner.
# Handles form submission, session state management, async coordinator invocation,
# and tab routing.

import asyncio
import traceback
import streamlit as st
from app.agents.coordinator import plan_trip
from app.ui.sidebar import render_sidebar
from app.ui.theme import get_custom_css
from app.ui.tabs.overview_tab import render_overview_tab
from app.ui.tabs.itinerary_tab import render_itinerary_tab
from app.ui.tabs.budget_tab import render_budget_tab
from app.ui.tabs.weather_tab import render_weather_tab
from app.ui.tabs.map_tab import render_map_tab
from app.ui.tabs.chat_tab import render_chat_tab

# Page Configuration
st.set_page_config(page_title="AI Travel Planner & Coordinator", layout="wide")


def run_async(coro):
    """
    Safely execute an asynchronous coroutine inside Streamlit's synchronous thread.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _plan_trip_with_status(state: dict):
    """
    Animate status transition messages while plan_trip graph executes.
    """
    messages = [
        "🔍 Geocoding destination and finding travel suggestions...",
        "🌦️ Querying live weather forecasts and historical climate data...",
        "🏰 Fetching local attractions from OpenStreetMap...",
        "🍜 Discovering highly-rated restaurants and local cuisine spots...",
        "🏨 Matching available hotels and accommodations...",
        "💰 Allocating per-category budget splits...",
        "🚗 Compiling local transit guides and walkability tips...",
        "🎒 Generating custom packing checklists...",
        "💱 Fetching exchange rates and cash advice...",
        "📝 Synthesizing final day-by-day itinerary summaries..."
    ]
    
    status_placeholder = st.empty()
    task = asyncio.create_task(plan_trip(state))
    
    idx = 0
    while not task.done():
        msg = messages[min(idx, len(messages) - 1)]
        status_placeholder.markdown(
            f"""
            <div style="background-color: #121824; border: 1px solid rgba(245, 158, 11, 0.2); padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.35);">
                <div style="display: flex; align-items: center;">
                    <div style="border: 3px solid rgba(245, 158, 11, 0.1); border-radius: 50%; border-top: 3px solid #F59E0B; width: 24px; height: 24px; animation: spin 1s linear infinite; margin-right: 12px;"></div>
                    <span style="font-family: 'Poppins', sans-serif; font-size: 1.05rem; font-weight: 500; color: #F8FAFC;">{msg}</span>
                </div>
            </div>
            <style>
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            </style>
            """,
            unsafe_allow_html=True
        )
        # Check task completion every 100ms for responsiveness
        for _ in range(30):
            if task.done():
                break
            await asyncio.sleep(0.1)
        idx += 1
        
    result = await task
    status_placeholder.empty()
    return result


def execute_plan_trip(inputs: dict):
    """
    Build the initial state and invoke the LangGraph coordinator workflow.
    """
    # 1. Initialize full TripState structure
    state = {
        "origin": inputs["origin"],
        "destination": inputs["destination"],
        "start_date": inputs["start_date"],
        "end_date": inputs["end_date"],
        "travelers": inputs["travelers"],
        "budget_total": inputs["budget_total"],
        "budget_currency": inputs["budget_currency"],
        "trip_type": inputs["trip_type"],
        "preferences": inputs["preferences"],
        # Special outputs init
        "destination_suggestions": None,
        "weather": None,
        "attractions": None,
        "restaurants": None,
        "hotels": None,
        "budget_breakdown": None,
        "transport_guide": None,
        "packing_list": None,
        "currency_info": None,
        "daily_itinerary": None,
        "errors": []
    }

    try:
        result = run_async(_plan_trip_with_status(state))
        st.session_state["trip_result"] = result
        # Store inputs separately to support instant regeneration
        st.session_state["trip_inputs"] = inputs
        
        # Clear chat history for a fresh trip
        if "chat_history" in st.session_state:
            del st.session_state["chat_history"]
            
        st.success("🎉 Travel Plan generated successfully!")
    except Exception as e:
        # Prevent app crash, show clean error box, dump trace to console
        st.error(
            "❌ An unexpected error occurred while generating your plan. "
            "Please check your API keys/connections and try again."
        )
        st.warning(f"Technical details: {e}")
        traceback.print_exc()


def main():
    # Inject Custom CSS Theme
    st.markdown(get_custom_css(), unsafe_allow_html=True)
    
    st.markdown(
        """
        <div class="main-title-container">
            <h1>🗺️ Premium AI Travel Planner</h1>
            <p>Configure parameters in the sidebar config panel to coordinate your complete custom itinerary, weather trends, budget visualizer, local transportation, and map pins.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Render sidebar inputs
    form_inputs = render_sidebar()

    # If sidebar is submitted, execute the plan
    if form_inputs:
        execute_plan_trip(form_inputs)

    # Initialize trip state cache if not present
    if "trip_result" not in st.session_state:
        st.session_state["trip_result"] = None
    if "trip_inputs" not in st.session_state:
        st.session_state["trip_inputs"] = None

    # Main area tabs display
    trip_result = st.session_state["trip_result"]
    
    if trip_result:
        # 3. Add Regenerate Button
        col1, col2 = st.columns([6, 1])
        with col2:
            if st.button("🔄 Regenerate Itinerary", help="Re-run the coordinator agents with the same input settings."):
                if st.session_state["trip_inputs"]:
                    execute_plan_trip(st.session_state["trip_inputs"])
                    # Rerun page to draw new results immediately
                    st.rerun()

        # 4. Wire Tabs
        tab_titles = [
            "📝 Overview",
            "📅 Itinerary",
            "💵 Budget & Currency",
            "🌦️ Weather & Packing",
            "🗺️ Interactive Map",
            "💬 AI Chat Assistant"
        ]
        
        tab_overview, tab_itinerary, tab_budget, tab_weather, tab_map, tab_chat = st.tabs(tab_titles)

        with tab_overview:
            render_overview_tab(trip_result)
            
        with tab_itinerary:
            render_itinerary_tab(trip_result)
            
        with tab_budget:
            render_budget_tab(trip_result)
            
        with tab_weather:
            render_weather_tab(trip_result)
            
        with tab_map:
            render_map_tab(trip_result)
            
        with tab_chat:
            render_chat_tab(trip_result)
    else:
        # Prompt to configure trip
        st.info("👈 Please configure your trip details in the sidebar and click **'Plan Trip'** to generate your plan.")


if __name__ == "__main__":
    main()

"""
Overview Tab UI component.
Displays trip title, overview, key stats, and user-friendly warnings for any errors.
"""
import streamlit as st
from app.agents.state import TripState
from app.ui.theme import render_stat_card_html


def render_overview_tab(trip_result: TripState):
    """
    Render the trip overview tab.
    
    Args:
        trip_result: Completed TripState dict.
    """
    itinerary = trip_result.get("daily_itinerary", [])
    
    # 1. Retrieve title and overview from metadata
    trip_title = "Your Travel Itinerary"
    overview = "Your personalized trip details are generated below."
    if itinerary and len(itinerary) > 0:
        trip_title = itinerary[0].get("_trip_title", trip_title)
        overview = itinerary[0].get("_overview", overview)

    st.markdown(f"### 🌴 {trip_title}")
    st.markdown(f"*{overview}*")
    st.write("---")

    # 2. Display key stats in custom cards
    st.subheader("📊 Trip Summary")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            render_stat_card_html(
                label="Destination",
                value=trip_result.get("destination", "Unknown"),
                icon="📍",
                accent_color="#F59E0B"
            ),
            unsafe_allow_html=True
        )
    with col2:
        dates_str = f"{trip_result.get('start_date', '?')} to {trip_result.get('end_date', '?')}"
        st.markdown(
            render_stat_card_html(
                label="Dates",
                value=dates_str,
                icon="📅",
                accent_color="#38BDF8"
            ),
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            render_stat_card_html(
                label="Travelers",
                value=f"{trip_result.get('travelers', 1)} people",
                icon="👥",
                accent_color="#10B981"
            ),
            unsafe_allow_html=True
        )
    with col4:
        budget_str = f"{trip_result.get('budget_total', 0.0):,.2f} {trip_result.get('budget_currency', 'USD')}"
        st.markdown(
            render_stat_card_html(
                label="Total Budget",
                value=budget_str,
                icon="💰",
                accent_color="#8B5CF6"
            ),
            unsafe_allow_html=True
        )

    # 3. User-friendly errors warning section
    errors = trip_result.get("errors", [])
    if errors:
        st.write("---")
        # Define clean, non-technical descriptions for agent-level errors
        friendly_error_map = {
            "destination_agent": "We had trouble finding destination suggestions. Some features may use defaults.",
            "weather_agent": "Live weather forecast could not be loaded; historical averages are shown instead.",
            "attraction_agent": "Attraction recommendation ranking was disrupted. Standard attractions are shown.",
            "restaurant_agent": "Restaurant recommendation ranking was disrupted. Standard restaurants are shown.",
            "hotel_agent": "Hotel availability details could not be loaded. AI-generated fallbacks are used.",
            "budget_agent": "We couldn't generate a custom budget breakdown; using default lodging/food allocations.",
            "transport_guide_agent": "Local transit and transport guides are temporarily unavailable.",
            "transport_agent": "Local transit and transport guides are temporarily unavailable.",
            "packing_agent": "We had trouble generating a custom packing list; using standard travel essentials.",
            "currency_agent": "Local currency exchange rate details are currently unavailable.",
            "summary_agent": "Some daily itinerary activities or descriptions may be incomplete."
        }

        # Deduplicate warnings to make them clean
        warnings_to_show = []
        for err in errors:
            agent = err.get("agent", "")
            msg = err.get("message", "")
            
            # Map specific agent or message keywords
            user_msg = friendly_error_map.get(agent)
            if not user_msg:
                if "placeholder" in msg.lower() or "incomplete" in msg.lower():
                    user_msg = "Some specific itinerary slots contain missing information placeholder messages."
                else:
                    user_msg = f"System notice for {agent.replace('_', ' ').title()}: data retrieval was degraded."
            
            if user_msg not in warnings_to_show:
                warnings_to_show.append(user_msg)

        if warnings_to_show:
            st.warning("⚠️ **Some parts of your itinerary details were partially degraded due to data retrieval issues:**")
            for warning in warnings_to_show:
                st.markdown(f"- {warning}")
            st.info("💡 You can click the **'Regenerate Itinerary'** button on the page to retry fetching complete information.")

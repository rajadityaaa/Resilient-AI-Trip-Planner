import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from app.agents.state import TripState
from app.ui.theme import get_plotly_layout_params


def render_weather_tab(trip_result: TripState):
    """
    Render weather forecasts and interactive checkboxes for packing items.
    
    Args:
        trip_result: Completed TripState dict.
    """
    st.subheader("🌦️ Weather Forecast & Packing Checklist")

    weather = trip_result.get("weather")
    packing = trip_result.get("packing_list", [])

    col1, col2 = st.columns(2)

    # 1. Weather forecast chart
    with col1:
        st.write("### 🌡️ Temperature Trends")
        if weather and isinstance(weather, dict) and weather.get("daily"):
            daily_w = weather.get("daily", [])
            
            # Show historical estimates info banner if applicable
            if weather.get("is_estimate"):
                st.info(
                    "📅 **Historical Estimates Notice:**\n"
                    "Since dates are outside the live forecast window, these temperatures represent "
                    "historical averages for this season, not a live forecast."
                )

            # Build DataFrame for Plotly Line chart
            dates = [d.get("date") for d in daily_w]
            temp_max = [float(d.get("temp_max", 0)) for d in daily_w]
            temp_min = [float(d.get("temp_min", 0)) for d in daily_w]
            conditions = [d.get("condition", "Clear") for d in daily_w]

            df_weather = pd.DataFrame({
                "Date": dates,
                "Max Temp (°C)": temp_max,
                "Min Temp (°C)": temp_min,
                "Condition": conditions
            })

            # Create interactive line chart
            fig_weather = go.Figure()
            fig_weather.add_trace(go.Scatter(
                x=df_weather["Date"],
                y=df_weather["Max Temp (°C)"],
                mode='lines+markers',
                name='Max Temp (°C)',
                line=dict(color='#FF6B6B', width=3)
            ))
            fig_weather.add_trace(go.Scatter(
                x=df_weather["Date"],
                y=df_weather["Min Temp (°C)"],
                mode='lines+markers',
                name='Min Temp (°C)',
                line=dict(color='#4D96FF', width=3)
            ))
            fig_weather.update_layout(
                title="Temperature Trend Across Trip Dates",
                xaxis_title="Date",
                yaxis_title="Temperature (°C)",
                margin=dict(t=40, b=40, l=40, r=40),
                **get_plotly_layout_params()
            )
            st.plotly_chart(fig_weather, use_container_width=True)

            # Mini forecast summaries
            st.write("**Daily Conditions Summary:**")
            lines = []
            for d in daily_w:
                lines.append(f"- **{d.get('date')}**: {d.get('condition')} ({d.get('temp_min',0):.0f}-{d.get('temp_max',0):.0f}°C)")
            st.markdown("\n".join(lines))
        else:
            st.info("Weather data is currently unavailable.")

    # 2. Packing Checklist
    with col2:
        st.write("### 🎒 Categorized Packing Checklist")
        if packing:
            # Grouping simple list items by keyword matching
            categories = {
                "🪪 Documents & Essentials": [],
                "👕 Clothing & Footwear": [],
                "🔌 Electronics & Chargers": [],
                "🧴 Health, Toiletries & Safety": [],
                "👜 Accessories & Other": []
            }

            for item in packing:
                item_lower = item.lower()
                
                # Check match criteria
                if any(x in item_lower for x in ["passport", "visa", "document", "currency", "cash", "card", "ticket", "insurance", "wallet", "identity", "permit"]):
                    categories["🪪 Documents & Essentials"].append(item)
                elif any(x in item_lower for x in ["clothing", "apparel", "shoes", "jacket", "coat", "poncho", "layer", "sandals", "socks", "swimwear", "swim", "pants", "shirt", "cotton", "hat", "umbrella"]):
                    categories["👕 Clothing & Footwear"].append(item)
                elif any(x in item_lower for x in ["adapter", "charger", "power bank", "phone", "electronics", "wi-fi", "camera", "battery"]):
                    categories["🔌 Electronics & Chargers"].append(item)
                elif any(x in item_lower for x in ["first aid", "medication", "toiletry", "sunscreen", "sunglasses", "insect", "repellent", "sanitizer", "towelettes", "toothbrush", "toothpaste", "medicine", "pill"]):
                    categories["🧴 Health, Toiletries & Safety"].append(item)
                else:
                    categories["👜 Accessories & Other"].append(item)

            # Render checkbox groups inside expanders
            checked_count = 0
            total_items = len(packing)

            # Let's render the lists category by category inside st.expanders
            for cat_name, cat_items in categories.items():
                if cat_items:
                    with st.expander(cat_name, expanded=True):
                        for item in cat_items:
                            # Unique keys for checkboxes to maintain state
                            key = f"pack_{item.replace(' ', '_').lower()}"
                            checked = st.checkbox(item, key=key)
                            if checked:
                                checked_count += 1
            st.write("")
            
            # Progress bar
            progress = checked_count / total_items if total_items > 0 else 0
            st.progress(progress)
            st.write(f"Completed **{checked_count}** of **{total_items}** packing items")
        else:
            st.info("Packing checklist is currently unavailable.")

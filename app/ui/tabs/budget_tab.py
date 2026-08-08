"""
Budget Tab UI component.
Visualizes budget breakdown and currency exchange data using Plotly charts.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from app.agents.state import TripState


from app.ui.theme import get_plotly_layout_params


def render_budget_tab(trip_result: TripState):
    """
    Render budget charts and exchange rate summaries.
    
    Args:
        trip_result: Completed TripState dict.
    """
    st.subheader("💵 Budget Allocation & Currency Conversion")

    breakdown = trip_result.get("budget_breakdown")
    total_budget = trip_result.get("budget_total", 0.0)
    currency = trip_result.get("budget_currency", "USD")

    if not breakdown:
        st.info("No budget breakdown data available.")
        return

    # 1. Currency Information Table
    currency_info = trip_result.get("currency_info")
    if currency_info:
        st.write("### 💱 Currency Summary")
        df_currency = pd.DataFrame([{
            "Original Budget": f"{total_budget:,.2f} {currency}",
            "Local Currency": currency_info.get("local_currency", "Unknown"),
            "Exchange Rate (1 USD/Base)": f"{currency_info.get('exchange_rate', 1.0):.5f}",
            "Converted Budget (Local)": f"{currency_info.get('converted_budget', total_budget):,.2f} {currency_info.get('local_currency', '')}"
        }])
        st.table(df_currency)
        
        # Display cash/tipping tips
        tips = currency_info.get("cash_tips")
        if tips:
            st.info(f"💵 **Cash & Tipping Guidance:**\n{tips}")

    # Layout for charts side-by-side
    col1, col2 = st.columns(2)

    with col1:
        st.write("### 📊 Allocation by Category")
        # Plotly Pie Chart
        categories = list(breakdown.keys())
        amounts = [float(v) for v in breakdown.values()]
        
        theme_colors = ["#F59E0B", "#10B981", "#3B82F6", "#EC4899", "#8B5CF6"]
        fig_pie = px.pie(
            names=categories,
            values=amounts,
            title="Budget Share",
            hole=0.4,
            color_discrete_sequence=theme_colors
        )
        fig_pie.update_layout(
            showlegend=True,
            margin=dict(t=40, b=0, l=0, r=0),
            **get_plotly_layout_params()
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        st.write("### ⚖️ Target Budget Verification")
        # Plotly Bar Chart comparing target vs sum
        allocated_sum = sum(amounts)
        
        fig_bar = go.Figure(data=[
            go.Bar(
                name="Allocated Budget",
                x=["Allocated Sum", "Target Budget"],
                y=[allocated_sum, total_budget],
                marker_color=["#3B82F6", "#F59E0B"]
            )
        ])
        fig_bar.update_layout(
            title="Allocated vs Target Target Match Check",
            yaxis_title=f"Amount ({currency})",
            margin=dict(t=40, b=40, l=40, r=40),
            showlegend=False,
            **get_plotly_layout_params()
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        difference = abs(allocated_sum - total_budget)
        if difference < 1.0:
            st.success("✅ Perfect allocation match: the sum of category items matches your target budget!")
        else:
            st.warning(f"⚠️ Allocation mismatch of {difference:.2f} {currency}. Sum of items: {allocated_sum:.2f}.")

"""
Insights Tab UI component.
Visualizes execution timing, parallel agent timeline (Gantt), agent status,
and platform-wide observability statistics.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.agents.state import TripState
from app.db import database as db
from app.ui.theme import get_plotly_layout_params


def render_insights_tab(trip_result: TripState) -> None:
    """
    Render agent timing breakdown, execution Gantt timeline,
    and historical platform averages.
    """
    st.subheader("⏱️ Execution Insights & Observability")

    timings = trip_result.get("timings") or {}
    total_dur = timings.get("total_duration_s")
    critical_path = timings.get("critical_path") or []
    agents_map: dict[str, dict[str, Any]] = timings.get("agents") or {}

    if not agents_map:
        st.info("No agent timing data available for this trip run.")
    else:
        # 1. Summary KPIs
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            st.metric("Total Execution Time", f"{total_dur:.2f}s" if total_dur is not None else "N/A")
        with col2:
            st.metric("Agents Executed", str(len(agents_map)))
        with col3:
            path_str = " ➔ ".join(critical_path) if critical_path else "N/A"
            st.metric("Critical Path (Slowest Chain)", path_str)

        # 2. Horizontal Gantt Chart
        st.write("### 📊 Agent Execution Timeline")

        # Sort agents by start_offset_s ascending
        sorted_agents = sorted(
            agents_map.values(),
            key=lambda a: (a.get("start_offset_s", 0.0), a.get("duration_s", 0.0)),
            reverse=True,  # reverse so earliest is at top of y-axis in horizontal bar
        )

        names = [a.get("name", "unknown") for a in sorted_agents]
        start_offsets = [a.get("start_offset_s", 0.0) for a in sorted_agents]
        durations = [a.get("duration_s", 0.0) for a in sorted_agents]
        statuses = [a.get("status", "done") for a in sorted_agents]
        sources = [a.get("source") or "internal/llm" for a in sorted_agents]
        fallbacks = ["Yes" if a.get("fallback_used") else "No" for a in sorted_agents]
        models = [a.get("llm_model") or "None" for a in sorted_agents]

        status_colors = {
            "done": "#10B981",     # emerald green
            "warn": "#F59E0B",     # amber
            "failed": "#EF4444",   # red
            "timeout": "#DC2626",  # dark red
        }
        bar_colors = [status_colors.get(s, "#3B82F6") for s in statuses]

        hover_texts = [
            f"<b>{n}</b><br>Start: {o:.2f}s<br>Duration: {d:.2f}s<br>Status: {s}<br>Source: {src}<br>Fallback: {fb}<br>Model: {m}"
            for n, o, d, s, src, fb, m in zip(names, start_offsets, durations, statuses, sources, fallbacks, models)
        ]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=durations,
                y=names,
                base=start_offsets,
                orientation="h",
                marker=dict(color=bar_colors, line=dict(color="rgba(255, 255, 255, 0.2)", width=1)),
                hovertext=hover_texts,
                hoverinfo="text",
            )
        )

        layout_params = get_plotly_layout_params()
        fig.update_layout(
            **layout_params,
            title="Agent Parallel Execution (Gantt View)",
            xaxis_title="Time from Start (seconds)",
            yaxis_title="Agent",
            height=max(360, len(names) * 35),
            barmode="stack",
            xaxis=dict(showgrid=True, gridcolor="rgba(255, 255, 255, 0.08)"),
            yaxis=dict(autorange="reversed"),
            margin=dict(l=120, r=30, t=50, b=50),
        )
        st.plotly_chart(fig, use_container_width=True)

        # 3. Agent Details Table
        st.write("### 📋 Agent Details")
        table_rows = []
        for a in sorted(agents_map.values(), key=lambda x: x.get("start_offset_s", 0.0)):
            table_rows.append({
                "Agent": a.get("name"),
                "Start Offset (s)": f"{a.get('start_offset_s', 0.0):.2f}",
                "Duration (s)": f"{a.get('duration_s', 0.0):.2f}",
                "Status": a.get("status"),
                "Source": a.get("source") or "—",
                "Fallback Used": "⚠️ Yes" if a.get("fallback_used") else "✅ No",
                "LLM Model": a.get("llm_model") or "—",
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # 4. Platform-wide Statistics
    st.divider()
    st.write("### 🌐 Platform Historical Averages")

    try:
        stats = db.get_stats()
    except Exception as exc:
        st.warning(f"Unable to read platform stats: {exc}")
        return

    if not stats or stats.get("total_trips", 0) == 0:
        st.info("No historical trips in the database yet.")
        return

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric("Total Trips", stats.get("total_trips", 0))
    with m2:
        sr = stats.get("success_rate", 0.0) * 100
        st.metric("Success Rate", f"{sr:.1f}%")
    with m3:
        p50 = stats.get("durations", {}).get("p50", 0.0)
        st.metric("p50 Duration", f"{p50:.2f}s")
    with m4:
        p95 = stats.get("durations", {}).get("p95", 0.0)
        st.metric("p95 Duration", f"{p95:.2f}s")
    with m5:
        avg = stats.get("durations", {}).get("avg", 0.0)
        st.metric("Avg Duration", f"{avg:.2f}s")
    with m6:
        st.metric("Last 24h Trips", stats.get("trips_last_24h", 0))

    # Agent averages breakdown if available
    agent_avgs = stats.get("average_duration_per_agent") or {}
    fb_rates = stats.get("fallback_rate_per_agent") or {}
    model_usage = stats.get("llm_model_usage") or {}

    col_a, col_b = st.columns(2)
    with col_a:
        if agent_avgs:
            st.write("#### ⏳ Average Agent Latency (s)")
            df_agent_stats = pd.DataFrame([
                {
                    "Agent": k,
                    "Avg Duration (s)": v,
                    "Fallback Rate": f"{(fb_rates.get(k, 0.0) * 100):.1f}%",
                }
                for k, v in sorted(agent_avgs.items(), key=lambda item: item[1], reverse=True)
            ])
            st.dataframe(df_agent_stats, use_container_width=True, hide_index=True)
    with col_b:
        if model_usage:
            st.write("#### 🤖 LLM Model Usage")
            df_models = pd.DataFrame([
                {"Model": k, "Calls": v}
                for k, v in sorted(model_usage.items(), key=lambda item: item[1], reverse=True)
            ])
            st.dataframe(df_models, use_container_width=True, hide_index=True)

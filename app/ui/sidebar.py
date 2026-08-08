"""
Sidebar UI: Input form for collecting trip details and user preferences.
"""
from datetime import datetime, date
from typing import Optional
import streamlit as st


def render_sidebar() -> Optional[dict]:
    """
    Render the sidebar form for collecting trip configuration parameters.
    Validates form inputs upon submission.
    
    Returns:
        Optional[dict]: A dictionary matching TripState's user input fields
                       on valid submission, else None.
    """
    # Render visual vector illustration above title
    svg_graphic = """
    <div style="text-align: center; margin-bottom: 10px;">
        <svg viewBox="0 0 100 45" width="100%" height="auto" style="border-radius:12px; background:linear-gradient(135deg, #1E293B, #0F172A); border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 4px 10px rgba(0,0,0,0.3);">
            <path d="M 0,45 L 25,25 L 45,35 L 75,15 L 100,45 Z" fill="rgba(245, 158, 11, 0.05)" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
            <path d="M 5,38 Q 35,32 70,18" fill="none" stroke="#F59E0B" stroke-dasharray="2,2" stroke-width="1.5" opacity="0.6"/>
            <!-- Airplane -->
            <g transform="translate(70, 18) rotate(-15) scale(0.65)">
                <path d="M0,0 L-10,-4 L-8,-1.5 L-14,0 L-8,1.5 L-10,4 Z" fill="#F59E0B" />
                <polygon points="-8,0 -3,-1 0,0 -3,1" fill="#FBBF24" />
            </g>
            <!-- Little city skyline silhouette in bottom right -->
            <rect x="75" y="38" width="5" height="7" fill="rgba(255,255,255,0.08)"/>
            <rect x="81" y="35" width="6" height="10" fill="rgba(255,255,255,0.06)"/>
            <rect x="88" y="32" width="4" height="13" fill="rgba(255,255,255,0.1)"/>
            <rect x="93" y="37" width="5" height="8" fill="rgba(255,255,255,0.05)"/>
        </svg>
    </div>
    """
    st.sidebar.markdown(svg_graphic, unsafe_allow_html=True)
    st.sidebar.title("✈️ Trip Planner Config")
    st.sidebar.markdown("Configure your trip parameters below:")

    with st.sidebar.form(key="trip_config_form"):
        st.markdown('<div class="sidebar-section-header">📍 Where & When</div>', unsafe_allow_html=True)
        origin = st.text_input(
            "Origin City",
            value="Delhi",
            placeholder="e.g. Delhi, London, New York"
        )
        
        destination = st.text_input(
            "Destination City (Optional)",
            value="Bangkok",
            placeholder="Leave blank for AI suggestions"
        )

        # Date range input in range mode (returns tuple: (start, end) or (start,))
        today = date.today()
        default_start = today
        default_end = today
        date_range = st.date_input(
            "Date Range",
            value=(default_start, default_end),
            min_value=today,
            help="Select both start and end dates."
        )

        travelers = st.number_input(
            "Number of Travelers",
            min_value=1,
            value=2,
            step=1
        )

        st.markdown('<div class="sidebar-section-header">💰 Budget & Style</div>', unsafe_allow_html=True)
        # Budget fields side-by-side or stacked
        budget_total = st.number_input(
            "Total Budget",
            min_value=0.0,
            value=1500.0,
            step=100.0
        )
        
        budget_currency = st.selectbox(
            "Budget Currency",
            options=["USD", "EUR", "INR", "GBP"],
            index=0
        )

        trip_type = st.selectbox(
            "Trip Type",
            options=["leisure", "business", "adventure", "family", "solo", "romantic"],
            index=3  # default to family
        )

        st.markdown('<div class="sidebar-section-header">❤️ Preferences</div>', unsafe_allow_html=True)
        # Preferences selection
        common_prefs = ["heritage", "food", "culture", "nightlife", "nature", "shopping", "adventure", "relaxation"]
        selected_prefs = st.multiselect(
            "Preferences",
            options=common_prefs,
            default=["heritage", "food", "culture"]
        )
        
        custom_prefs_input = st.text_input(
            "Custom Preferences (comma-separated)",
            placeholder="e.g. museums, local music, photography"
        )

        submit_button = st.form_submit_button(label="Plan Trip")

    if submit_button:
        # ── Form Validation ──
        errors = []

        # 1. Origin validation
        if not origin.strip():
            errors.append("Origin City cannot be empty.")

        # 2. Date range validation
        start_date = None
        end_date = None
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date_val, end_date_val = date_range
            if start_date_val and end_date_val:
                if end_date_val <= start_date_val:
                    errors.append("End date must be after start date.")
                else:
                    start_date = start_date_val.strftime("%Y-%m-%d")
                    end_date = end_date_val.strftime("%Y-%m-%d")
            else:
                errors.append("Please select both a start date and an end date.")
        else:
            errors.append("Please select a complete date range (both start and end dates).")

        # 3. Budget validation
        if budget_total <= 0:
            errors.append("Total Budget must be greater than 0.")

        if errors:
            for err in errors:
                st.sidebar.error(err)
            return None

        # ── Merge Preferences ──
        all_preferences = list(selected_prefs)
        if custom_prefs_input.strip():
            custom_list = [p.strip().lower() for p in custom_prefs_input.split(",") if p.strip()]
            for cp in custom_list:
                if cp not in all_preferences:
                    all_preferences.append(cp)

        return {
            "origin": origin.strip(),
            "destination": destination.strip() if destination.strip() else None,
            "start_date": start_date,
            "end_date": end_date,
            "travelers": int(travelers),
            "budget_total": float(budget_total),
            "budget_currency": budget_currency,
            "trip_type": trip_type,
            "preferences": all_preferences,
        }

    return None

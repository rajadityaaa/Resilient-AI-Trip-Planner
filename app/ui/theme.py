"""
Theme Module: Custom CSS rules, Plotly layout parameters, and reusable HTML
snippet helpers for the premium AI Travel Planner UI.

Helper functions (render_*) return raw HTML strings that should be injected
via st.markdown(..., unsafe_allow_html=True).  They centralise all markup so
tab modules never duplicate styling.
"""

import textwrap
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────────────────

def get_custom_css() -> str:
    """Return the complete custom CSS block for injection into Streamlit."""
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

    /* ── Global Body Font override ─────────────────────────────────────── */
    html, body, [class*="css"], .stApp {
        font-family: 'Inter', sans-serif;
        background-color: #0E131F;
        color: #E2E8F0;
    }

    /* ── Main Title Styling with subtle gradient ────────────────────────── */
    .main-title-container {
        background: linear-gradient(135deg, #182235, #0F172A);
        padding: 25px 30px;
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        margin-bottom: 25px;
    }

    .main-title-container h1 {
        font-family: 'Poppins', sans-serif;
        font-weight: 700;
        color: #F8FAFC;
        margin: 0 0 8px 0 !important;
    }

    .main-title-container p {
        color: #94A3B8 !important;
        margin: 0 !important;
        font-size: 0.95rem;
    }

    /* ── Sidebar form layout enhancements ──────────────────────────────── */
    [data-testid="stSidebar"] {
        background-color: #0B0E14;
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }

    [data-testid="stSidebar"] [data-testid="stForm"] {
        background-color: #121824;
        border-radius: 12px !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        padding: 20px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3) !important;
    }

    /* ── Section Headings in sidebar ───────────────────────────────────── */
    .sidebar-section-header {
        font-family: 'Poppins', sans-serif;
        font-size: 0.9rem;
        font-weight: 600;
        color: #F59E0B;
        margin-top: 15px;
        margin-bottom: 8px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        padding-bottom: 4px;
        letter-spacing: 0.5px;
    }

    /* ── Buttons: unified 0.2 s ease transition ─────────────────────────── */
    .stButton > button {
        font-family: 'Poppins', sans-serif;
        font-weight: 500;
        background-color: #F59E0B !important;
        color: #0E131F !important;
        border-radius: 30px !important;
        border: none !important;
        padding: 8px 24px !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease !important;
        box-shadow: 0 4px 10px rgba(245, 158, 11, 0.3) !important;
    }

    .stButton > button:hover {
        transform: scale(1.05) translateY(-1px) !important;
        box-shadow: 0 8px 20px rgba(245, 158, 11, 0.55) !important;
        background-color: #FBBF24 !important;
    }

    .stButton > button:active {
        transform: scale(0.97) !important;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.3) !important;
    }

    /* ── Download button — same pill treatment ──────────────────────────── */
    .stDownloadButton > button {
        font-family: 'Poppins', sans-serif;
        font-weight: 500;
        background-color: #1E293B !important;
        color: #F8FAFC !important;
        border-radius: 30px !important;
        border: 1px solid rgba(245, 158, 11, 0.4) !important;
        padding: 8px 22px !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25) !important;
    }

    .stDownloadButton > button:hover {
        transform: scale(1.04) translateY(-1px) !important;
        border-color: rgba(245, 158, 11, 0.8) !important;
        box-shadow: 0 6px 16px rgba(245, 158, 11, 0.35) !important;
    }

    .stDownloadButton > button:active {
        transform: scale(0.97) !important;
    }

    /* ── Link buttons (Search & Book) ───────────────────────────────────── */
    [data-testid="stLinkButton"] > a {
        font-family: 'Poppins', sans-serif !important;
        font-weight: 500 !important;
        border-radius: 30px !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease !important;
    }

    [data-testid="stLinkButton"] > a:hover {
        transform: scale(1.04) translateY(-1px) !important;
        box-shadow: 0 6px 16px rgba(59, 130, 246, 0.35) !important;
        opacity: 0.92 !important;
    }

    [data-testid="stLinkButton"] > a:active {
        transform: scale(0.97) !important;
    }

    /* ── Checkbox hover glow ────────────────────────────────────────────── */
    [data-testid="stCheckbox"] {
        transition: opacity 0.2s ease !important;
    }

    [data-testid="stCheckbox"]:hover {
        opacity: 0.85 !important;
    }

    [data-testid="stCheckbox"] label {
        transition: color 0.2s ease !important;
    }

    [data-testid="stCheckbox"]:hover label {
        color: #F8FAFC !important;
    }

    /* ── Glassmorphism Stat Cards (Overview tab) ────────────────────────── */
    .stat-card {
        background: rgba(24, 34, 53, 0.65);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-radius: 14px;
        padding: 20px 22px 18px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
        position: relative;
        overflow: hidden;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .stat-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        border-radius: 14px 14px 0 0;
        background: var(--card-accent, #F59E0B);
        opacity: 0.85;
    }

    .stat-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45),
                    0 0 0 1px rgba(255, 255, 255, 0.06),
                    0 0 24px var(--card-glow, rgba(245, 158, 11, 0.15));
    }

    .stat-card-icon {
        font-size: 1.4rem;
        margin-bottom: 8px;
        line-height: 1;
    }

    .stat-card-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.72rem;
        text-transform: uppercase;
        color: #64748B;
        letter-spacing: 1.2px;
        margin-bottom: 6px;
    }

    .stat-card-value {
        font-family: 'Poppins', sans-serif;
        font-size: 1.2rem;
        font-weight: 700;
        color: #F1F5F9;
        margin: 0;
        line-height: 1.3;
    }

    /* ── Legacy .overview-card (kept for backward compat) ─────────────── */
    .overview-card {
        background-color: #182235;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
        transition: transform 0.2s ease;
    }

    .overview-card:hover {
        transform: translateY(-2px);
        border-color: rgba(245, 158, 11, 0.3);
    }

    .overview-card-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.75rem;
        text-transform: uppercase;
        color: #94A3B8;
        letter-spacing: 1px;
        margin-bottom: 5px;
    }

    .overview-card-value {
        font-family: 'Poppins', sans-serif;
        font-size: 1.25rem;
        font-weight: 700;
        color: #F1F5F9;
        margin: 0;
    }

    /* ── Hero / Empty-state section ─────────────────────────────────────── */
    .hero-section {
        text-align: center;
        padding: 60px 20px 50px;
    }

    .hero-headline {
        font-family: 'Poppins', sans-serif;
        font-size: clamp(2rem, 5vw, 3.2rem);
        font-weight: 700;
        background: linear-gradient(135deg, #F59E0B 0%, #38BDF8 55%, #8B5CF6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0 0 18px 0;
        line-height: 1.15;
        letter-spacing: -0.5px;
    }

    .hero-sub {
        font-family: 'Inter', sans-serif;
        font-size: 1.1rem;
        color: #94A3B8;
        margin: 0 auto 48px auto;
        max-width: 540px;
        line-height: 1.6;
    }

    .feature-cards-row {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        justify-content: center;
        max-width: 860px;
        margin: 0 auto;
    }

    .feature-card {
        background: rgba(24, 34, 53, 0.55);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px 22px 20px;
        width: 185px;
        text-align: center;
        cursor: default;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
        position: relative;
        overflow: hidden;
    }

    .feature-card::after {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: 16px;
        background: linear-gradient(135deg, rgba(255,255,255,0.04) 0%, transparent 60%);
        pointer-events: none;
    }

    .feature-card:hover {
        transform: translateY(-6px);
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5),
                    0 0 0 1px rgba(245, 158, 11, 0.2);
        border-color: rgba(245, 158, 11, 0.35);
    }

    .feature-card-icon {
        font-size: 2rem;
        margin-bottom: 12px;
        display: block;
    }

    .feature-card-title {
        font-family: 'Poppins', sans-serif;
        font-size: 0.88rem;
        font-weight: 600;
        color: #F1F5F9;
        margin: 0 0 6px 0;
    }

    .feature-card-desc {
        font-family: 'Inter', sans-serif;
        font-size: 0.75rem;
        color: #64748B;
        margin: 0;
        line-height: 1.5;
    }

    .hero-cta-hint {
        margin-top: 40px;
        font-family: 'Inter', sans-serif;
        font-size: 0.9rem;
        color: #475569;
    }

    .hero-cta-hint span {
        color: #F59E0B;
        font-weight: 600;
    }

    /* ── Itinerary Timeline ─────────────────────────────────────────────── */
    .timeline-container {
        position: relative;
        padding: 8px 0 24px 0;
    }

    .timeline-item {
        display: flex;
        gap: 20px;
        margin-bottom: 28px;
        position: relative;
    }

    .timeline-left {
        display: flex;
        flex-direction: column;
        align-items: center;
        flex-shrink: 0;
        width: 44px;
    }

    .timeline-node {
        width: 44px;
        height: 44px;
        border-radius: 50%;
        background: linear-gradient(135deg, #F59E0B, #FBBF24);
        color: #0E131F;
        font-family: 'Poppins', sans-serif;
        font-weight: 700;
        font-size: 1rem;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.2), 0 4px 12px rgba(245, 158, 11, 0.3);
        z-index: 1;
    }

    .timeline-connector {
        flex: 1;
        width: 2px;
        background: linear-gradient(to bottom, rgba(245, 158, 11, 0.4), rgba(245, 158, 11, 0.05));
        min-height: 24px;
        margin-top: 4px;
    }

    .timeline-card {
        flex: 1;
        background: rgba(18, 24, 36, 0.8);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        padding: 20px 22px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .timeline-card:hover {
        transform: translateX(4px);
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4),
                    0 0 0 1px rgba(245, 158, 11, 0.12);
    }

    .timeline-card-header {
        font-family: 'Poppins', sans-serif;
        font-size: 1rem;
        font-weight: 600;
        color: #F8FAFC;
        margin: 0 0 16px 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .timeline-card-date {
        font-family: 'Inter', sans-serif;
        font-size: 0.78rem;
        color: #64748B;
        font-weight: 400;
        margin-left: auto;
    }

    .timeline-period {
        margin-bottom: 14px;
    }

    .timeline-period-label {
        font-family: 'Poppins', sans-serif;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 4px;
    }

    .timeline-period-label.morning  { color: #FCD34D; }
    .timeline-period-label.afternoon { color: #38BDF8; }
    .timeline-period-label.evening  { color: #C084FC; }

    .timeline-period-text {
        font-family: 'Inter', sans-serif;
        font-size: 0.88rem;
        color: #CBD5E1;
        line-height: 1.6;
        margin: 0;
    }

    .timeline-notes {
        margin-top: 14px;
        background: rgba(245, 158, 11, 0.07);
        border-left: 3px solid #F59E0B;
        border-radius: 0 8px 8px 0;
        padding: 10px 14px;
        font-family: 'Inter', sans-serif;
        font-size: 0.83rem;
        color: #E2E8F0;
        line-height: 1.55;
    }

    .timeline-notes strong {
        color: #F59E0B;
    }

    /* ── Tab content fade-in animation ──────────────────────────────────── */
    @keyframes tabFadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0);   }
    }

    .stTabs [data-baseweb="tab-panel"] {
        animation: tabFadeIn 0.25s ease forwards;
    }

    /* ── Itinerary section header (kept for compat) ──────────────────── */
    .itinerary-section-header {
        font-family: 'Poppins', sans-serif;
        font-size: 1.05rem;
        font-weight: 600;
        color: #38BDF8;
        margin-top: 10px;
        margin-bottom: 5px;
    }

    /* ── Collapsible expanders ───────────────────────────────────────── */
    .streamlit-expanderHeader {
        background-color: #121824 !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 8px !important;
    }

    /* ── Custom divider line ─────────────────────────────────────────── */
    hr {
        border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
    }

    /* ── Itinerary day badge ──────────────────────────────────────────── */
    .day-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background-color: #F59E0B;
        color: #0E131F;
        font-weight: 700;
        font-size: 0.85rem;
        margin-right: 10px;
    }

    /* ── App Footer ───────────────────────────────────────────────────── */
    .app-footer {
        margin-top: 56px;
        padding: 20px 24px;
        border-top: 1px solid rgba(255, 255, 255, 0.07);
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        font-family: 'Inter', sans-serif;
        font-size: 0.8rem;
        color: #475569;
    }

    .footer-left {
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .footer-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
    }

    .footer-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 500;
        font-family: 'Inter', sans-serif;
        line-height: 1;
        white-space: nowrap;
    }

    .footer-pill.streamlit  { background: rgba(255, 75, 75, 0.12);  color: #FF6B6B; border: 1px solid rgba(255, 75, 75, 0.25); }
    .footer-pill.langgraph  { background: rgba(16, 185, 129, 0.12); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.25); }
    .footer-pill.gemini     { background: rgba(59, 130, 246, 0.12); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.25); }
    .footer-pill.python     { background: rgba(251, 191, 36, 0.12); color: #FBBF24; border: 1px solid rgba(251, 191, 36, 0.25); }
    .footer-pill.folium     { background: rgba(139, 92, 246, 0.12); color: #A78BFA; border: 1px solid rgba(139, 92, 246, 0.25); }

    </style>
    """


# ──────────────────────────────────────────────────────────────────────────────
# HTML Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

def _clean_html(html_str: str) -> str:
    """Strip leading and trailing whitespace from every line to prevent Markdown from interpreting indented lines as code blocks."""
    return "\n".join(line.strip() for line in html_str.splitlines() if line.strip())


def render_hero_section() -> str:
    """
    Return the HTML for the landing / empty-state hero section shown before
    a trip plan has been generated.  Inject via st.markdown(..., unsafe_allow_html=True).
    """
    return _clean_html("""
    <div class="hero-section">
        <h1 class="hero-headline">Your Next Adventure,<br>Planned by AI</h1>
        <p class="hero-sub">
            Fill in the sidebar with your destination, dates, and budget —
            our multi-agent AI will craft a complete itinerary, weather brief,
            packing list, and budget plan in seconds.
        </p>

        <div class="feature-cards-row">
            <div class="feature-card">
                <span class="feature-card-icon">🗺️</span>
                <div class="feature-card-title">Smart Itineraries</div>
                <div class="feature-card-desc">Day-by-day plans tailored to your trip style and duration.</div>
            </div>
            <div class="feature-card">
                <span class="feature-card-icon">💰</span>
                <div class="feature-card-title">Budget Planning</div>
                <div class="feature-card-desc">Auto-split budgets with live currency conversion.</div>
            </div>
            <div class="feature-card">
                <span class="feature-card-icon">🌦️</span>
                <div class="feature-card-title">Weather-Aware Packing</div>
                <div class="feature-card-desc">Forecasts + categorised packing checklists per destination.</div>
            </div>
            <div class="feature-card">
                <span class="feature-card-icon">💬</span>
                <div class="feature-card-title">AI Chat Assistant</div>
                <div class="feature-card-desc">Ask questions or tweak your itinerary with a built-in AI chat.</div>
            </div>
        </div>

        <p class="hero-cta-hint">👈 Configure your trip in the <span>sidebar</span> and click <span>Plan Trip</span> to begin.</p>
    </div>
    """)


def render_stat_card_html(
    label: str,
    value: str,
    icon: str = "📌",
    accent_color: str = "#F59E0B",
) -> str:
    """
    Return HTML for a single glassmorphism stat card.

    Args:
        label:        Short label shown above the value (e.g. "Destination").
        value:        Primary value string displayed prominently.
        icon:         Emoji icon shown at the top of the card.
        accent_color: CSS colour for the top border accent and hover glow.

    Returns:
        HTML string to inject via st.markdown(..., unsafe_allow_html=True).
    """
    return _clean_html(f"""
    <div class="stat-card" style="--card-accent: {accent_color}; --card-glow: {accent_color}33;">
        <div class="stat-card-icon">{icon}</div>
        <div class="stat-card-label">{label}</div>
        <div class="stat-card-value">{value}</div>
    </div>
    """)


def _escape_html(text: str) -> str:
    """Minimal HTML-escape for user-supplied text inserted into markup."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def render_timeline_html(itinerary: list) -> str:
    """
    Return HTML for the full day-by-day itinerary timeline.

    Each day becomes a node on a vertical timeline line connected to a card
    that shows morning / afternoon / evening sections and optional notes.

    Args:
        itinerary: List of day dicts from TripState["daily_itinerary"].

    Returns:
        HTML string to inject via st.markdown(..., unsafe_allow_html=True).
    """
    if not itinerary:
        return "<p style='color:#64748B;'>No itinerary data available.</p>"

    items_html = []
    last_idx = len(itinerary) - 1

    for idx, day in enumerate(itinerary):
        day_num  = day.get("day", idx + 1)
        day_date = _escape_html(str(day.get("date", "")))
        morning  = _escape_html(str(day.get("morning",   "Free time / exploring.")))
        afternoon = _escape_html(str(day.get("afternoon", "Free time / exploring.")))
        evening  = _escape_html(str(day.get("evening",   "Leisure / return to hotel.")))
        notes    = day.get("notes", "")

        notes_html = ""
        if notes:
            notes_html = f"""
            <div class="timeline-notes">
                <strong>💡 Day {day_num} Notes &amp; Reminders:</strong><br>
                {_escape_html(str(notes))}
            </div>"""

        # Only draw the connector line between days (not after the last one)
        connector = '<div class="timeline-connector"></div>' if idx < last_idx else ""

        items_html.append(f"""
        <div class="timeline-item">
            <div class="timeline-left">
                <div class="timeline-node">{day_num}</div>
                {connector}
            </div>
            <div class="timeline-card">
                <div class="timeline-card-header">
                    Day {day_num}
                    <span class="timeline-card-date">{day_date}</span>
                </div>
                <div class="timeline-period">
                    <div class="timeline-period-label morning">🌅 Morning</div>
                    <p class="timeline-period-text">{morning}</p>
                </div>
                <div class="timeline-period">
                    <div class="timeline-period-label afternoon">☀️ Afternoon</div>
                    <p class="timeline-period-text">{afternoon}</p>
                </div>
                <div class="timeline-period">
                    <div class="timeline-period-label evening">🌌 Evening</div>
                    <p class="timeline-period-text">{evening}</p>
                </div>
                {notes_html}
            </div>
        </div>""")

    return _clean_html(f'<div class="timeline-container">{"".join(items_html)}</div>')


def render_footer_html() -> str:
    """
    Return HTML for the small footer rendered at the bottom of the page.

    Returns:
        HTML string to inject via st.markdown(..., unsafe_allow_html=True).
    """
    return _clean_html("""
    <div class="app-footer">
        <div class="footer-left">
            <span>AI Travel Planner &amp; Coordinator</span>
        </div>
        <div class="footer-pills">
            <span class="footer-pill streamlit">🎈 Streamlit</span>
            <span class="footer-pill langgraph">🔗 LangGraph</span>
            <span class="footer-pill gemini">✦ Gemini</span>
            <span class="footer-pill python">🐍 Python</span>
            <span class="footer-pill folium">🗺️ Folium</span>
        </div>
    </div>
    """)



# ──────────────────────────────────────────────────────────────────────────────
# Plotly layout helpers (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

def get_plotly_layout_params() -> dict:
    """Return common Plotly styling parameters to match our dark theme."""
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor":  "rgba(0,0,0,0)",
        "font":          dict(family="Inter, sans-serif", color="#E2E8F0"),
        "title_font":    dict(family="Poppins, sans-serif", size=14, color="#F8FAFC")
    }

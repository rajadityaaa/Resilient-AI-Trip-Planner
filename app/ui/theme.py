"""
Theme Module: Custom CSS rules and Plotly layout parameters for premium visual design.
"""

def get_custom_css() -> str:
    """Return the custom CSS rules for injection into Streamlit."""
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

    /* Global Body Font override */
    html, body, [class*="css"], .stApp {
        font-family: 'Inter', sans-serif;
        background-color: #0E131F;
        color: #E2E8F0;
    }

    /* Main Title Styling with subtle gradient */
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

    /* Sidebar form layout enhancements */
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

    /* Section Headings in sidebar */
    .sidebar-section-header {
        font-family: 'Poppins', sans-serif;
        font-size: 0.9rem;
        font-weight: 600;
        color: #F59E0B; /* warm gold accent */
        margin-top: 15px;
        margin-bottom: 8px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        padding-bottom: 4px;
        letter-spacing: 0.5px;
    }

    /* Pill-shaped buttons with hover animations */
    .stButton>button {
        font-family: 'Poppins', sans-serif;
        font-weight: 500;
        background-color: #F59E0B !important; /* Gold */
        color: #0E131F !important;
        border-radius: 30px !important;
        border: none !important;
        padding: 8px 24px !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
        box-shadow: 0 4px 10px rgba(245, 158, 11, 0.3) !important;
    }

    .stButton>button:hover {
        transform: scale(1.05) !important;
        box-shadow: 0 6px 15px rgba(245, 158, 11, 0.5) !important;
        background-color: #FBBF24 !important; /* Lighter gold */
    }

    .stButton>button:active {
        transform: scale(0.98) !important;
    }

    /* Styled Metric Cards for Overview tab */
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
        transition: transform 0.2s;
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

    /* Itinerary tab header badge styling */
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
    
    .itinerary-section-header {
        font-family: 'Poppins', sans-serif;
        font-size: 1.05rem;
        font-weight: 600;
        color: #38BDF8; /* Sky blue */
        margin-top: 10px;
        margin-bottom: 5px;
    }

    /* Collapsible list expanders styling */
    .streamlit-expanderHeader {
        background-color: #121824 !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 8px !important;
    }
    
    /* Custom divider line */
    hr {
        border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
    }
    </style>
    """


def get_plotly_layout_params() -> dict:
    """Return common Plotly styling parameters to match our dark theme."""
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": dict(family="Inter, sans-serif", color="#E2E8F0"),
        "title_font": dict(family="Poppins, sans-serif", size=14, color="#F8FAFC")
    }

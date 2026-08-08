"""
PDF Tools: Converts itinerary and trip plan into downloadable PDF using fpdf2.
Handles Unicode / non-ASCII characters cleanly using DejaVuSans.
"""
import os
import requests
from pathlib import Path
from fpdf import FPDF
from app.agents.state import TripState

# Font configuration
RESOURCES_DIR = Path(__file__).parent.parent / "resources"
FONT_PATH = RESOURCES_DIR / "DejaVuSans.ttf"
FONT_BOLD_PATH = RESOURCES_DIR / "DejaVuSans-Bold.ttf"

# URLs to download fonts if missing
DEJAVU_REGULAR_URL = "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/resources/fonts/dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf"
DEJAVU_BOLD_URL = "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/resources/fonts/dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf"


def _ensure_fonts_exist():
    """Ensure DejaVuSans fonts are downloaded and cached locally."""
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Download regular font
    if not FONT_PATH.exists():
        try:
            response = requests.get(DEJAVU_REGULAR_URL, timeout=15)
            response.raise_for_status()
            FONT_PATH.write_bytes(response.content)
        except Exception as e:
            # Fallback to local Windows Arial font if download fails
            win_font = Path("C:/Windows/Fonts/arial.ttf")
            if win_font.exists():
                FONT_PATH.write_bytes(win_font.read_bytes())
            else:
                raise RuntimeError(f"Could not load DejaVuSans or Arial font: {e}")

    # Download bold font
    if not FONT_BOLD_PATH.exists():
        try:
            response = requests.get(DEJAVU_BOLD_URL, timeout=15)
            response.raise_for_status()
            FONT_BOLD_PATH.write_bytes(response.content)
        except Exception as e:
            # Fallback to local Windows Arial Bold font if download fails
            win_font_bold = Path("C:/Windows/Fonts/arialbd.ttf")
            if win_font_bold.exists():
                FONT_BOLD_PATH.write_bytes(win_font_bold.read_bytes())
            else:
                raise RuntimeError(f"Could not load DejaVuSans-Bold or Arial Bold font: {e}")


def export_itinerary_pdf(trip_result: TripState) -> bytes:
    """
    Generate a clean, readable PDF from trip state.
    
    Args:
        trip_result: Completed TripState dict.
        
    Returns:
        bytes: Binary PDF data.
    """
    _ensure_fonts_exist()
    
    pdf = FPDF()
    pdf.add_page()
    
    # Register Unicode font
    pdf.add_font("DejaVuSans", "", str(FONT_PATH))
    pdf.add_font("DejaVuSans", "B", str(FONT_BOLD_PATH))
    pdf.set_font("DejaVuSans", size=12)

    # 1. Document Title
    itinerary = trip_result.get("daily_itinerary", [])
    title_text = "Your Travel Itinerary"
    overview_text = ""
    if itinerary and len(itinerary) > 0:
        title_text = itinerary[0].get("_trip_title", title_text)
        overview_text = itinerary[0].get("_overview", "")

    pdf.set_font("DejaVuSans", "B", 18)
    pdf.cell(0, 10, title_text, ln=True, align="C")
    pdf.set_font("DejaVuSans", "", 10)
    pdf.cell(0, 8, f"Destination: {trip_result.get('destination', 'Unknown')}", ln=True, align="C")
    pdf.cell(0, 8, f"Dates: {trip_result.get('start_date', '?')} to {trip_result.get('end_date', '?')}", ln=True, align="C")
    pdf.ln(5)

    # 2. Overview Section
    if overview_text:
        pdf.set_font("DejaVuSans", "B", 12)
        pdf.cell(0, 8, "Overview", ln=True)
        pdf.set_font("DejaVuSans", "", 10)
        pdf.multi_cell(0, 5, overview_text)
        pdf.ln(5)

    # 3. Day-by-Day Itinerary Schedule
    if itinerary:
        pdf.set_font("DejaVuSans", "B", 14)
        pdf.cell(0, 10, "Daily Schedule", ln=True)
        
        for day in itinerary:
            pdf.set_font("DejaVuSans", "B", 11)
            pdf.cell(0, 8, f"Day {day.get('day', '?')} — {day.get('date', '?')}", ln=True)
            pdf.set_font("DejaVuSans", "", 10)
            
            # Morning
            pdf.set_font("DejaVuSans", "B", 10)
            pdf.write(5, "Morning: ")
            pdf.set_font("DejaVuSans", "", 10)
            pdf.write(5, day.get("morning", "Free time") + "\n")
            
            # Afternoon
            pdf.set_font("DejaVuSans", "B", 10)
            pdf.write(5, "Afternoon: ")
            pdf.set_font("DejaVuSans", "", 10)
            pdf.write(5, day.get("afternoon", "Free time") + "\n")
            
            # Evening
            pdf.set_font("DejaVuSans", "B", 10)
            pdf.write(5, "Evening: ")
            pdf.set_font("DejaVuSans", "", 10)
            pdf.write(5, day.get("evening", "Free time") + "\n")
            
            # Notes
            notes = day.get("notes", "")
            if notes:
                pdf.set_font("DejaVuSans", "B", 10)
                pdf.write(5, "Notes: ")
                pdf.set_font("DejaVuSans", "", 10)
                pdf.write(5, notes + "\n")
            
            pdf.ln(4)

    # 4. Budget Summary Table
    breakdown = trip_result.get("budget_breakdown")
    total_budget = trip_result.get("budget_total", 0.0)
    currency = trip_result.get("budget_currency", "USD")

    if breakdown:
        pdf.add_page()
        pdf.set_font("DejaVuSans", "B", 14)
        pdf.cell(0, 10, "Budget Summary Table", ln=True)
        pdf.set_font("DejaVuSans", "", 10)
        
        # Draw table header
        pdf.set_font("DejaVuSans", "B", 10)
        pdf.cell(90, 8, "Category", border=1)
        pdf.cell(90, 8, f"Amount ({currency})", border=1, ln=True)
        pdf.set_font("DejaVuSans", "", 10)

        for category, amount in breakdown.items():
            pdf.cell(90, 8, category.capitalize(), border=1)
            pdf.cell(90, 8, f"{float(amount):,.2f}", border=1, ln=True)
            
        pdf.set_font("DejaVuSans", "B", 10)
        pdf.cell(90, 8, "Total Allocated Sum", border=1)
        pdf.cell(90, 8, f"{sum(float(v) for v in breakdown.values()):,.2f}", border=1, ln=True)
        pdf.cell(90, 8, "Target Total Budget", border=1)
        pdf.cell(90, 8, f"{total_budget:,.2f}", border=1, ln=True)

    # 5. Output as bytes
    pdf_output = pdf.output()
    return bytes(pdf_output)

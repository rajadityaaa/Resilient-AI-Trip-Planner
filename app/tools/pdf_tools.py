"""
PDF Tools: Converts itinerary and trip plan into downloadable PDF using fpdf2.
Supports multi-script rendering (Latin, Thai, Devanagari) with Noto Sans fonts,
text shaping via uharfbuzz, emoji mapping, and safe unbroken string wrapping.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import WrapMode, XPos, YPos

from app.agents.state import TripState

logger = logging.getLogger(__name__)

# Font directory resolved relative to this package (no absolute paths or downloads)
FONTS_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts"

# Common emoji and symbol mappings to clean plain text
EMOJI_MAP: dict[str, str] = {
    "🗺️": "[Map]",
    "🗺": "[Map]",
    "✈️": "[Flight]",
    "✈": "[Flight]",
    "🏨": "[Hotel]",
    "🍽️": "[Restaurant]",
    "🍽": "[Restaurant]",
    "🍴": "[Food]",
    "🏛️": "[Attraction]",
    "🏛": "[Attraction]",
    "⛩️": "[Temple]",
    "⛩": "[Temple]",
    "🌦️": "[Weather]",
    "🌦": "[Weather]",
    "☀️": "[Sunny]",
    "🌧️": "[Rain]",
    "🌧": "[Rain]",
    "💵": "[Budget]",
    "💱": "[Currency]",
    "📅": "[Calendar]",
    "📝": "[Overview]",
    "💬": "[Chat]",
    "⏱️": "[Time]",
    "⏱": "[Time]",
    "📊": "[Chart]",
    "📋": "[Details]",
    "🌐": "[Platform]",
    "🎒": "[Packing]",
    "🚌": "[Transit]",
    "🚗": "[Car]",
    "🚶": "[Walk]",
    "📍": "[Pin]",
    "⚠️": "[Warning]",
    "✅": "[OK]",
    "❌": "[Error]",
    "🎉": "[Celebration]",
    "⏳": "[Waiting]",
    "⚪": "[Pending]",
    "—": "-",
    "–": "-",
    "➔": "->",
    "→": "->",
    "•": "*",
}

# Cached set of supported unicode codepoints across loaded Noto fonts
_SUPPORTED_CODEPOINTS: Optional[set[int]] = None


def _get_supported_codepoints() -> set[int]:
    """Inspect TTF cmap tables to find all supported character codepoints."""
    global _SUPPORTED_CODEPOINTS
    if _SUPPORTED_CODEPOINTS is not None:
        return _SUPPORTED_CODEPOINTS

    codepoints: set[int] = set()
    if FONTS_DIR.exists():
        for font_file in FONTS_DIR.glob("*.ttf"):
            try:
                tt = TTFont(font_file)
                for table in tt["cmap"].tables:
                    codepoints.update(table.cmap.keys())
            except Exception as exc:
                logger.warning(f"[PDF] Could not inspect font {font_file}: {exc}")

    # Always support standard whitespace and ascii control codes
    codepoints.update({ord("\n"), ord("\r"), ord("\t"), ord(" ")})
    _SUPPORTED_CODEPOINTS = codepoints
    return _SUPPORTED_CODEPOINTS


def sanitize_pdf_text(text: Optional[str]) -> str:
    """
    Sanitize text for PDF generation:
    1. Map common emojis and symbols to text descriptions.
    2. Replace any remaining unsupported characters with '?' to prevent missing glyph warnings.
    """
    if not text:
        return ""

    res = str(text)
    for em, replacement in EMOJI_MAP.items():
        if em in res:
            res = res.replace(em, replacement)

    supported = _get_supported_codepoints()
    if supported:
        res = "".join(c if ord(c) in supported else "?" for c in res)

    return res


def _register_fonts(pdf: FPDF) -> str:
    """
    Register Noto fonts and fallbacks.
    Returns the primary font family name to use.
    If font files are missing, logs a warning and degrades gracefully.
    """
    font_definitions = [
        ("NotoSans", "", FONTS_DIR / "NotoSans-Regular.ttf"),
        ("NotoSans", "B", FONTS_DIR / "NotoSans-Bold.ttf"),
        ("NotoSansThai", "", FONTS_DIR / "NotoSansThai-Regular.ttf"),
        ("NotoSansThai", "B", FONTS_DIR / "NotoSansThai-Bold.ttf"),
        ("NotoSansDevanagari", "", FONTS_DIR / "NotoSansDevanagari-Regular.ttf"),
        ("NotoSansDevanagari", "B", FONTS_DIR / "NotoSansDevanagari-Bold.ttf"),
    ]

    loaded_families: set[str] = set()
    for family, style, path in font_definitions:
        if path.exists():
            try:
                pdf.add_font(family, style, str(path))
                loaded_families.add(family)
            except Exception as exc:
                logger.warning(f"[PDF] Failed to add font {family} ({style}) from {path}: {exc}")
        else:
            logger.warning(f"[PDF] Font file not found: {path}. Skipping {family} ({style}).")

    if "NotoSans" in loaded_families:
        primary_font = "NotoSans"
        fallbacks = [f for f in ["NotoSansThai", "NotoSansDevanagari"] if f in loaded_families]
        if fallbacks:
            try:
                pdf.set_fallback_fonts(fallbacks)
            except Exception as exc:
                logger.warning(f"[PDF] Could not set fallback fonts {fallbacks}: {exc}")
    else:
        logger.warning("[PDF] NotoSans font family not loaded. Falling back to built-in helvetica.")
        primary_font = "helvetica"

    # Enable text shaping for complex scripts (Thai, Devanagari) if uharfbuzz is available
    try:
        pdf.set_text_shaping(True)
    except Exception as exc:
        logger.warning(f"[PDF] Text shaping could not be enabled: {exc}")

    return primary_font


def export_itinerary_pdf(trip_result: TripState) -> bytes:
    """
    Generate a clean, readable PDF from trip state.

    Args:
        trip_result: Completed TripState dict.

    Returns:
        bytes: Binary PDF data.
    """
    pdf = FPDF()
    pdf.add_page()

    font_family = _register_fonts(pdf)
    pdf.set_font(font_family, size=12)

    # 1. Document Title
    itinerary = trip_result.get("daily_itinerary") or []
    title_text = "Your Travel Itinerary"
    overview_text = ""
    if itinerary and len(itinerary) > 0 and isinstance(itinerary[0], dict):
        title_text = itinerary[0].get("_trip_title") or title_text
        overview_text = itinerary[0].get("_overview") or ""

    pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 18)
    pdf.multi_cell(
        0, 10, sanitize_pdf_text(title_text), align="C",
        wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )

    pdf.set_font(font_family, size=10)
    dest_str = f"Destination: {trip_result.get('destination', 'Unknown')}"
    pdf.multi_cell(
        0, 7, sanitize_pdf_text(dest_str), align="C",
        wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )

    dates_str = f"Dates: {trip_result.get('start_date', '?')} to {trip_result.get('end_date', '?')}"
    pdf.multi_cell(
        0, 7, sanitize_pdf_text(dates_str), align="C",
        wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.ln(5)

    # 2. Overview Section
    if overview_text:
        pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 12)
        pdf.multi_cell(
            0, 8, "Overview",
            wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.set_font(font_family, size=10)
        pdf.multi_cell(
            0, 5, sanitize_pdf_text(overview_text),
            wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.ln(5)

    # 3. Day-by-Day Itinerary Schedule
    if itinerary:
        pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 14)
        pdf.multi_cell(
            0, 10, "Daily Schedule",
            wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

        for day in itinerary:
            if not isinstance(day, dict):
                continue
            pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 11)
            day_header = f"Day {day.get('day', '?')} - {day.get('date', '?')}"
            pdf.multi_cell(
                0, 8, sanitize_pdf_text(day_header),
                wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )

            # Day time blocks
            blocks = [
                ("Morning", day.get("morning", "Free time")),
                ("Afternoon", day.get("afternoon", "Free time")),
                ("Evening", day.get("evening", "Free time")),
            ]
            for label, content in blocks:
                pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 10)
                pdf.write(5, f"{label}: ")
                pdf.set_font(font_family, size=10)
                pdf.multi_cell(
                    0, 5, sanitize_pdf_text(str(content)),
                    wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
                )

            notes = day.get("notes")
            if notes:
                pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 10)
                pdf.write(5, "Notes: ")
                pdf.set_font(font_family, size=10)
                pdf.multi_cell(
                    0, 5, sanitize_pdf_text(str(notes)),
                    wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
                )

            pdf.ln(4)

    # 4. Budget Summary Table
    breakdown = trip_result.get("budget_breakdown")
    total_budget = trip_result.get("budget_total", 0.0)
    currency = trip_result.get("budget_currency", "USD")

    if breakdown and isinstance(breakdown, dict):
        pdf.add_page()
        pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 14)
        pdf.multi_cell(
            0, 10, "Budget Summary Table",
            wrapmode=WrapMode.CHAR, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

        # Table header
        pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 10)
        pdf.cell(90, 8, "Category", border=1)
        pdf.cell(90, 8, sanitize_pdf_text(f"Amount ({currency})"), border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font(font_family, size=10)
        for category, amount in breakdown.items():
            cat_name = str(category).capitalize()
            amt_str = f"{float(amount):,.2f}" if isinstance(amount, (int, float)) else str(amount)
            pdf.cell(90, 8, sanitize_pdf_text(cat_name), border=1)
            pdf.cell(90, 8, amt_str, border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font(font_family, "B" if font_family != "helvetica" else "", 10)
        allocated_sum = sum(float(v) for v in breakdown.values() if isinstance(v, (int, float)))
        pdf.cell(90, 8, "Total Allocated Sum", border=1)
        pdf.cell(90, 8, f"{allocated_sum:,.2f}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(90, 8, "Target Total Budget", border=1)
        pdf.cell(90, 8, f"{float(total_budget):,.2f}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 5. Output PDF bytes
    return bytes(pdf.output())

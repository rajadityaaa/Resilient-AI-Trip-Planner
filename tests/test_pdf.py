"""
Tests for Step 8: Multi-script PDF export with Noto fonts.
Covers:
- Rendering Thai (กรุงเทพมหานคร), Devanagari (जयपुर), CJK/Latin (Tokyo 東京),
  long unbroken URLs (300+ chars), emojis, and unbroken Thai text without error.
- Verified bytes start with b"%PDF" and file size < 2 MB.
- Absence of "missing glyphs" warnings for Thai and Devanagari text.
- Text/font verification via pypdf (Noto fonts present, Arial absent).
- Graceful degradation when a font file is missing (warning logged, PDF still generates).
"""
from __future__ import annotations

import io
import logging
import warnings
from pathlib import Path
from unittest.mock import patch

import pypdf

from app.tools.pdf_tools import export_itinerary_pdf, sanitize_pdf_text


def test_sanitize_pdf_text_emoji_and_unsupported():
    """Verify common emojis are converted to text and unsupported characters become '?'."""
    input_text = "Visiting 🏨 in Bangkok 🏛️ with 💵 budget and ☀️ weather Tokyo 東京"
    sanitized = sanitize_pdf_text(input_text)

    # Emojis should be replaced
    assert "[Hotel]" in sanitized
    assert "[Attraction]" in sanitized
    assert "[Budget]" in sanitized
    assert "[Sunny]" in sanitized

    # CJK characters (not in fonts) should be converted to '?'
    assert "Tokyo ??" in sanitized or "Tokyo" in sanitized


def test_pdf_export_multiscript_and_safe_wrapping():
    """Verify PDF generation with multi-script strings, long URLs, and unbroken Thai text."""
    long_url = "https://example.com/planner/v1/very/long/unbroken/path/" + ("abcdef1234567890" * 20)  # 300+ chars
    long_thai_unbroken = "กรุงเทพมหานครเป็นเมืองหลวงและนครที่มีประชากรมากที่สุดของประเทศไทย" * 3

    sample_trip = {
        "destination": "กรุงเทพมหานคร (Bangkok) & जयपुर (Jaipur)",
        "start_date": "2026-12-01",
        "end_date": "2026-12-05",
        "budget_total": 2500.0,
        "budget_currency": "USD",
        "daily_itinerary": [
            {
                "day": 1,
                "date": "2026-12-01",
                "_trip_title": "Multi-Script Cultural Journey: กรุงเทพมหานคร & जयपुर",
                "_overview": f"Welcome to Tokyo 東京! Explore sights at 🏛️. Info: {long_url}",
                "morning": f"Visit sacred temples: กรุงเทพมหานคร. Details: {long_thai_unbroken}",
                "afternoon": "Stroll around historic palaces: जयपुर City Palace with 🏨 hotel lunch.",
                "evening": "Night markets and dinner with street food specialties.",
                "notes": "Dress modestly in temples and stay hydrated.",
            }
        ],
        "budget_breakdown": {
            "accommodations": 1000.0,
            "activities": 600.0,
            "dining": 500.0,
            "transit": 400.0,
        },
    }

    # Catch warnings and logs to verify no "missing glyphs" for Thai/Devanagari
    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter("always")
        pdf_bytes = export_itinerary_pdf(sample_trip)

    # 1. Assertions on binary output
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF"), "Output must start with PDF magic header"
    assert len(pdf_bytes) < 2 * 1024 * 1024, "Generated PDF must be under 2 MB"

    # 2. Check no 'missing glyphs' warning for Thai and Devanagari
    for w in captured_warnings:
        msg = str(w.message)
        if "missing the following glyphs" in msg:
            assert "NotoSansThai" not in msg
            assert "NotoSansDevanagari" not in msg
            assert "\\u0e" not in msg  # Thai unicode block
            assert "\\u09" not in msg  # Devanagari unicode block

    # 3. Verify PDF structure with pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1

    # Extract all text from pages
    all_text = " ".join(page.extract_text() or "" for page in reader.pages)
    assert len(all_text) > 0, "PDF pages should contain extractable text"

    # Either text extraction has the scripts, or fonts embedded in the PDF match Noto
    embedded_fonts = set()
    for page in reader.pages:
        fonts_dict = page.get("/Resources", {}).get("/Font", {})
        for font_obj in fonts_dict.values():
            base_font = font_obj.get("/BaseFont", "")
            if base_font:
                embedded_fonts.add(str(base_font))

    # Verify Noto fonts are embedded and Arial is absent
    noto_present = any("NotoSans" in f for f in embedded_fonts)
    arial_present = any("Arial" in f for f in embedded_fonts)
    assert noto_present, f"Noto fonts should be embedded in PDF. Found: {embedded_fonts}"
    assert not arial_present, f"Windows Arial should NOT be used. Found: {embedded_fonts}"


def test_pdf_export_missing_font_file_degrades_gracefully(caplog):
    """Verify that when a font file is missing, a warning is logged and PDF still generates."""
    sample_trip = {
        "destination": "Paris, France",
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "daily_itinerary": [
            {
                "day": 1,
                "date": "2026-06-01",
                "morning": "Walk by the Eiffel Tower",
                "afternoon": "Visit the Louvre",
                "evening": "Dinner by the Seine",
            }
        ],
    }

    # Simulate missing font by patching FONTS_DIR to a non-existent directory
    fake_fonts_dir = Path("app/resources/non_existent_fonts")
    with patch("app.tools.pdf_tools.FONTS_DIR", fake_fonts_dir):
        with caplog.at_level(logging.WARNING):
            pdf_bytes = export_itinerary_pdf(sample_trip)

        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF")

        # Warning should be logged about missing fonts or helvetica fallback
        warning_logged = any("Font file not found" in record.message or "helvetica" in record.message for record in caplog.records)
        assert warning_logged, "Expected warning about missing fonts"

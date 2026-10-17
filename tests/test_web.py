"""
Tests for Web UI Integration & Backend Additions.
Covers:
- Root static mount returns index.html (200 text/html)
- /api/unknown returns JSON 404 (never index.html)
- /docs and /health remain accessible
- Privacy hardening: /api/trips returns 404 when ENV != 'development'
- /api/share/{slug}/pdf returns 200 application/pdf (%PDF) and safe filename
- /api/chat provides assistant response
- Content-Security-Policy header attached to static responses only
- Static file integrity: checks all linked CSS, JS, fonts, and images exist locally with zero CDN scripts
"""
from __future__ import annotations

import html.parser
import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.config import get_settings
from app.db import database as db

client = TestClient(app, raise_server_exceptions=False)
WEB_DIR = Path(__file__).resolve().parent.parent / "app" / "web"


# ── 1. Static Mount & Routing Tests ──────────────────────────────────────────

def test_root_returns_html_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Aetheria" in response.text
    assert "<!DOCTYPE html>" in response.text


def test_plan_page_and_redirect():
    # 1. /plan redirects to /plan/
    res_redirect = client.get("/plan", follow_redirects=False)
    assert res_redirect.status_code in (301, 302, 307, 308)
    assert res_redirect.headers.get("location") == "/plan/"

    # 2. /plan/ returns 200 text/html
    res_plan = client.get("/plan/")
    assert res_plan.status_code == 200
    assert "text/html" in res_plan.headers.get("content-type", "")
    assert "Autonomous Journey Engine" in res_plan.text
    assert "<!DOCTYPE html>" in res_plan.text


def test_no_video_tags_anywhere():
    """Enforce strict rule: Zero video tags anywhere in web templates."""
    for html_file in WEB_DIR.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        assert "<video" not in content.lower(), f"Prohibited <video> tag found in {html_file.name}"


def test_landing_page_budget():
    """Ensure landing page HTML+CSS+JS transfer budget <= 150 KB (excluding images)."""
    index_path = WEB_DIR / "index.html"
    assert index_path.exists()
    html_size = index_path.stat().st_size

    # Linked CSS and JS on landing page
    linked_css_size = sum(f.stat().st_size for f in [
        WEB_DIR / "css" / "tokens.css",
        WEB_DIR / "css" / "base.css",
        WEB_DIR / "css" / "layout.css",
        WEB_DIR / "css" / "components.css",
        WEB_DIR / "css" / "sections" / "hero.css",
        WEB_DIR / "css" / "landing.css",
    ] if f.exists())

    linked_js_size = sum(f.stat().st_size for f in [
        WEB_DIR / "js" / "landing.js",
    ] if f.exists())

    total_bundle = html_size + linked_css_size + linked_js_size
    assert total_bundle <= 150 * 1024, f"Landing bundle exceeds 150 KB budget: {total_bundle / 1024:.1f} KB"


def test_all_plan_buttons_point_to_plan():
    """Every 'Plan my trip' or planning button on landing page must link to /plan/."""
    index_path = WEB_DIR / "index.html"
    content = index_path.read_text(encoding="utf-8")
    
    # Check all <a ...> tags containing 'plan'
    a_regex = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    for match in a_regex.finditer(content):
        href = match.group(1)
        text = match.group(2)
        if "plan" in text.lower():
            assert href.startswith("/plan/"), f"Planning button has invalid href '{href}' in text '{text.strip()}'"


def test_docs_and_health_remain_functional():
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json().get("status") == "ok"

    res_docs = client.get("/docs")
    assert res_docs.status_code == 200


def test_unknown_api_path_returns_json_404_not_html():
    response = client.get("/api/nonexistent_route_test")
    assert response.status_code == 404
    assert "application/json" in response.headers.get("content-type", "")
    assert "API route '/api/nonexistent_route_test' not found." in response.json().get("detail", "")


# ── 2. CSP Header Test ────────────────────────────────────────────────────────

def test_content_security_policy_header():
    # Static root must carry CSP
    res_root = client.get("/")
    assert "content-security-policy" in res_root.headers
    csp = res_root.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp

    # /api and /health should NOT have static CSP attached
    res_health = client.get("/health")
    assert "content-security-policy" not in res_health.headers


# ── 3. Privacy Hardening on /api/trips ────────────────────────────────────────

def test_api_trips_privacy_hardening(monkeypatch):
    settings = get_settings()

    # When ENV is 'production' or 'staging', GET /api/trips must return 404
    monkeypatch.setattr(settings, "ENV", "production")
    res_prod = client.get("/api/trips")
    assert res_prod.status_code == 404

    # When ENV is 'development', GET /api/trips returns 200 list
    monkeypatch.setattr(settings, "ENV", "development")
    res_dev = client.get("/api/trips")
    assert res_dev.status_code == 200
    assert isinstance(res_dev.json(), list)


# ── 4. PDF Download by Share Slug ────────────────────────────────────────────

def test_pdf_download_endpoint_by_slug(tmp_path):
    # Seed a sample trip in SQLite DB
    trip_id = "test-trip-pdf-123"
    slug = "test-slug-pdf-456"
    test_result = {
        "destination": "Santorini, Greece",
        "start_date": "2026-10-01",
        "end_date": "2026-10-05",
        "budget_total": 2000,
        "budget_currency": "EUR",
        "daily_itinerary": [
            {
                "day": 1,
                "date": "2026-10-01",
                "_trip_title": "Santorini Odyssey",
                "_overview": "Spectacular cliffs and caldera sunsets.",
                "morning": "Walk through Oia village.",
                "afternoon": "Boat tour around volcano.",
                "evening": "Sunset dinner.",
                "notes": "Carry sunscreen.",
            }
        ],
        "budget_breakdown": {"accommodations": 1000, "food": 600, "transit": 400},
    }

    db.save_trip(
        trip_id,
        share_slug=slug,
        status="done",
        request_obj={"destination": "Santorini"},
        result_obj=test_result,
    )

    # 1. Unknown slug -> 404
    res_unknown = client.get("/api/share/nonexistent-slug/pdf")
    assert res_unknown.status_code == 404

    # 2. Known slug -> 200 application/pdf
    res_pdf = client.get(f"/api/share/{slug}/pdf")
    assert res_pdf.status_code == 200
    assert res_pdf.headers.get("content-type") == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF")
    assert "attachment; filename=" in res_pdf.headers.get("content-disposition", "")


# ── 5. Chat Assistant Endpoint ────────────────────────────────────────────────

def test_chat_assistant_endpoint():
    trip_id = "test-chat-trip-789"
    slug = "test-chat-slug-012"
    test_result = {
        "destination": "Kyoto, Japan",
        "attractions": [{"name": "Fushimi Inari", "category": "Shrine"}],
        "restaurants": [{"name": "Gion Karyo", "cuisine": "Kaiseki"}],
    }
    db.save_trip(
        trip_id,
        share_slug=slug,
        status="done",
        request_obj={"destination": "Kyoto"},
        result_obj=test_result,
    )

    # Mock LLM to avoid external network/quota consumption
    with patch("app.llm.factory.get_llm") as mock_get_llm:
        def mock_llm_instance(prompt, system_instruction):
            return "You can visit Fushimi Inari early in the morning for serenity."

        mock_get_llm.return_value = mock_llm_instance

        payload = {
            "trip_id_or_slug": slug,
            "message": "When should I visit the shrine?",
        }
        res_chat = client.post("/api/chat", json=payload)
        assert res_chat.status_code == 200
        data = res_chat.json()
        assert "reply" in data
        assert "Fushimi Inari" in data["reply"]


# ── 6. Static File & HTML Link Integrity (Stdlib HTMLParser) ──────────────────

class StaticResourceExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.local_links: list[str] = []
        self.external_scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)

        # Scripts
        if tag == "script" and "src" in attr_dict:
            src = attr_dict["src"]
            if src.startswith(("http://", "https://", "//")):
                self.external_scripts.append(src)
            else:
                self.local_links.append(src)

        # Links (CSS, preloads)
        if tag == "link" and "href" in attr_dict:
            href = attr_dict["href"]
            if not href.startswith(("http://", "https://", "#", "mailto:")):
                self.local_links.append(href)

        # Images & Sources
        if tag == "img" and "src" in attr_dict:
            src = attr_dict["src"]
            if not src.startswith(("http://", "https://", "data:")):
                self.local_links.append(src)

        if tag == "source" and "srcset" in attr_dict:
            srcset = attr_dict["srcset"]
            for part in srcset.split(","):
                cand = part.strip().split(" ")[0]
                if cand and not cand.startswith(("http://", "https://")):
                    self.local_links.append(cand)


def test_index_html_static_integrity():
    index_path = WEB_DIR / "index.html"
    assert index_path.exists(), "app/web/index.html must exist."

    html_content = index_path.read_text(encoding="utf-8")
    parser = StaticResourceExtractor()
    parser.feed(html_content)

    # 1. Confirm zero external CDN scripts
    assert len(parser.external_scripts) == 0, f"Found prohibited external CDN scripts: {parser.external_scripts}"

    # 2. Confirm all referenced local files exist on disk
    for rel_path in parser.local_links:
        clean_path = rel_path.split("?")[0].split("#")[0]
        full_path = (WEB_DIR / clean_path).resolve()
        assert full_path.exists(), f"Referenced asset does not exist: {rel_path} (looked at {full_path})"


def test_plan_html_static_integrity():
    plan_index_path = WEB_DIR / "plan" / "index.html"
    assert plan_index_path.exists(), "app/web/plan/index.html must exist."

    html_content = plan_index_path.read_text(encoding="utf-8")
    parser = StaticResourceExtractor()
    parser.feed(html_content)

    # 1. Confirm zero external CDN scripts
    assert len(parser.external_scripts) == 0, f"Found prohibited external CDN scripts in /plan/: {parser.external_scripts}"

    # 2. Confirm all referenced local files exist on disk
    doc_dir = WEB_DIR / "plan"
    for rel_path in parser.local_links:
        clean_path = rel_path.split("?")[0].split("#")[0]
        full_path = (doc_dir / clean_path).resolve()
        assert full_path.exists(), f"Referenced asset in /plan/ does not exist: {rel_path} (looked at {full_path})"


def test_css_url_integrity():
    """Verify all url(...) in CSS files resolve to existing files."""
    css_files = list((WEB_DIR / "css").rglob("*.css"))
    assert len(css_files) > 0

    url_regex = re.compile(r"url\(['\"]?([^'\")]+)['\"]?\)")

    for css_file in css_files:
        content = css_file.read_text(encoding="utf-8")
        for match in url_regex.finditer(content):
            target = match.group(1)
            if target.startswith("data:"):
                continue
            resolved = (css_file.parent / target).resolve()
            assert resolved.exists(), f"Broken CSS url reference: '{target}' in {css_file.name} (looked for {resolved})"

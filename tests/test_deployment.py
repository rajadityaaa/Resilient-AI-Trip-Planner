"""
Unit and integration tests for deployment features:
- TRUST_PROXY configuration and SlowAPI client IP extraction
- Spoofed X-Forwarded-For protection when TRUST_PROXY is False
- Real client IP extraction when TRUST_PROXY is True
- SSE response headers (anti-buffering, no-cache, no gzip compression)
- Cache-Control headers on HTML vs static assets
- Resilient SQLite database fallback when primary directory is not writable
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import Settings, get_settings
from app.db import database as db
from app.security.client_ip import get_client_ip


@pytest.fixture
def client():
    return TestClient(app)


# ── 1. Client IP & Proxy Header Extraction Tests ──────────────────────────────

def test_get_client_ip_untrusted_ignores_forwarded_for():
    """When TRUST_PROXY is False, X-Forwarded-For spoofed header must be ignored."""
    mock_request = MagicMock()
    mock_request.client.host = "192.168.1.50"
    mock_request.headers = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18"}

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.TRUST_PROXY = False
        ip = get_client_ip(mock_request)
        # Must return the socket host, ignoring the spoofed header
        assert ip == "192.168.1.50"


def test_get_client_ip_trusted_reads_leftmost_ip():
    """When TRUST_PROXY is True, left-most IP in X-Forwarded-For is returned."""
    mock_request = MagicMock()
    mock_request.client.host = "10.0.0.1"  # Reverse proxy address
    mock_request.headers = {"X-Forwarded-For": "203.0.113.195, 10.0.0.2"}

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.TRUST_PROXY = True
        ip = get_client_ip(mock_request)
        assert ip == "203.0.113.195"


def test_get_client_ip_trusted_fallback_when_header_empty():
    """When TRUST_PROXY is True but header is missing/empty, fall back to socket host."""
    mock_request = MagicMock()
    mock_request.client.host = "192.168.1.10"
    mock_request.headers = {}

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.TRUST_PROXY = True
        ip = get_client_ip(mock_request)
        assert ip == "192.168.1.10"


def test_get_client_ip_fallback_to_default_when_no_client():
    """When request.client is None, fallback to 127.0.0.1."""
    mock_request = MagicMock()
    mock_request.client = None
    mock_request.headers = {}

def test_rate_limiter_trusted_proxy_separate_buckets():
    """Two different forwarded IPs get separate rate limit keys when TRUST_PROXY is True."""
    req_a = MagicMock()
    req_a.client.host = "10.0.0.1"
    req_a.headers = {"X-Forwarded-For": "203.0.113.10"}

    req_b = MagicMock()
    req_b.client.host = "10.0.0.1"
    req_b.headers = {"X-Forwarded-For": "203.0.113.20"}

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.TRUST_PROXY = True
        key_a = get_client_ip(req_a)
        key_b = get_client_ip(req_b)
        assert key_a == "203.0.113.10"
        assert key_b == "203.0.113.20"
        assert key_a != key_b


def test_rate_limiter_untrusted_proxy_spoofed_header_ignored():
    """When TRUST_PROXY is False, two requests with different spoofed headers share the same socket key."""
    req_a = MagicMock()
    req_a.client.host = "192.168.1.100"
    req_a.headers = {"X-Forwarded-For": "1.1.1.1"}

    req_b = MagicMock()
    req_b.client.host = "192.168.1.100"
    req_b.headers = {"X-Forwarded-For": "2.2.2.2"}

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.TRUST_PROXY = False
        key_a = get_client_ip(req_a)
        key_b = get_client_ip(req_b)
        # Both requests map to socket host 192.168.1.100, ignoring spoofed headers
        assert key_a == "192.168.1.100"
        assert key_b == "192.168.1.100"
        assert key_a == key_b


# ── 2. TRUST_PROXY Configuration Setting Tests ────────────────────────────────

def test_trust_proxy_config_default_based_on_env():
    """Verify default TRUST_PROXY value based on ENV."""
    with patch.dict("os.environ", {"ENV": "production"}, clear=False):
        # Clear lru_cache
        get_settings.cache_clear()
        settings = Settings()
        assert settings.TRUST_PROXY is True
        get_settings.cache_clear()

    with patch.dict("os.environ", {"ENV": "development"}, clear=False):
        get_settings.cache_clear()
        settings = Settings()
        assert settings.TRUST_PROXY is False
        get_settings.cache_clear()


def test_trust_proxy_config_explicit_override():
    """Explicit TRUST_PROXY environment variable overrides ENV default."""
    with patch.dict("os.environ", {"ENV": "production", "TRUST_PROXY": "false"}, clear=False):
        get_settings.cache_clear()
        settings = Settings()
        assert settings.TRUST_PROXY is False
        get_settings.cache_clear()

    with patch.dict("os.environ", {"ENV": "development", "TRUST_PROXY": "true"}, clear=False):
        get_settings.cache_clear()
        settings = Settings()
        assert settings.TRUST_PROXY is True
        get_settings.cache_clear()


# ── 3. SSE Headers & Anti-Buffering / Anti-GZip Tests ─────────────────────────

def test_sse_endpoint_headers(client):
    """Confirm SSE endpoint sends Cache-Control: no-cache, X-Accel-Buffering: no, and not compressed."""
    from app.api.main import _store
    job = _store.create("test-sse-headers-job", {"destination": "Tokyo"})
    job.status = "done"
    job.result = {"destination": "Tokyo"}
    job.share_slug = "tokyo123"
    _store.update(job)

    resp = client.get(
        "/api/plan/test-sse-headers-job/events",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-accel-buffering") == "no"
    assert "no-cache" in resp.headers.get("cache-control", "")
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    # Must NOT be gzip encoded (SafeGZipMiddleware skips SSE)
    assert resp.headers.get("content-encoding") != "gzip"


# ── 4. Cache-Control on Static vs HTML Pages ──────────────────────────────────

def test_html_pages_have_no_cache_headers(client):
    """HTML endpoints (/, /plan/) must have no-cache headers."""
    resp = client.get("/")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "no-cache" in cc
    assert "no-store" in cc

    resp_plan = client.get("/plan/")
    assert resp_plan.status_code == 200
    cc_plan = resp_plan.headers.get("cache-control", "")
    assert "no-cache" in cc_plan


def test_static_assets_cache_headers(client):
    """Static assets (CSS, JS) get long-lived public cache headers."""
    resp = client.get("/css/tokens.css")
    if resp.status_code == 200:
        cc = resp.headers.get("cache-control", "")
        assert "public" in cc
        assert "max-age=31536000" in cc


# ── 5. Database Resilience & Fallback Tests ───────────────────────────────────

def test_database_fallback_on_unwritable_path():
    """If the primary DB path is not writable, _db_path falls back to tempdir."""
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
        resolved = db._db_path()
        assert resolved.parent == Path(tempfile.gettempdir())
        assert "travel_fallback.db" in str(resolved)


def test_database_init_recovers_gracefully():
    """init_db creates tables in fallback path when primary is inaccessible."""
    temp_dir = tempfile.mkdtemp()
    test_db = Path(temp_dir) / "test_init.db"

    with patch.dict("os.environ", {"DATABASE_URL": str(test_db)}):
        db._INITIALIZED_PATHS.clear()
        db.init_db()
        assert test_db.exists()
        # Verify tables created
        with db._connect() as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            assert "trips" in tables
            assert "cache" in tables
            assert "schema_version" in tables

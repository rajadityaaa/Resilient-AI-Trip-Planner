#!/usr/bin/env python3
"""
Production smoke test script for AI Travel Planner Agent.
Standard library only (no external dependencies).

Usage:
    python scripts/smoke_test.py https://ai-travel-planner.onrender.com
    python scripts/smoke_test.py http://localhost:8000 --plan
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple


def _make_request(
    url: str,
    method: str = "GET",
    data: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 15.0,
) -> Tuple[int, Dict[str, str], bytes]:
    """Perform HTTP request using stdlib urllib and return (status, headers, body)."""
    req_headers = {"User-Agent": "SmokeTest/1.0"}
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    # Permissive SSL context for development / self-signed certs if any
    ctx = ssl.create_default_context()

    req = urllib.request.Request(
        url=url,
        data=body_bytes,
        headers=req_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp_headers, resp.read()
    except urllib.error.HTTPError as err:
        resp_headers = {k.lower(): v for k, v in err.headers.items()}
        return err.code, resp_headers, err.read()
    except Exception as exc:
        raise RuntimeError(f"Connection failed to {url}: {exc}") from exc


def wait_for_health(base_url: str, max_wait_s: int = 90) -> dict:
    """Poll /health until 200 OK or timeout (handles free-tier cold starts)."""
    health_url = f"{base_url}/health"
    print(f"[*] Probing {health_url} (cold-start window up to {max_wait_s}s)...")
    start_t = time.time()
    attempt = 0

    while time.time() - start_t < max_wait_s:
        attempt += 1
        elapsed = time.time() - start_t
        try:
            status, _, body = _make_request(health_url, timeout=5.0)
            if status == 200:
                data = json.loads(body.decode("utf-8"))
                print(
                    f"    [OK] /health responded 200 OK in {elapsed:.1f}s (attempt {attempt}). "
                    f"env={data.get('env')}, version={data.get('version')}, key_configured={data.get('llm_key_configured')}"
                )
                return data
            else:
                print(f"    [WAIT] /health returned status {status} ({elapsed:.1f}s elapsed, retry in 3s)...")
        except Exception as exc:
            print(f"    [WAIT] Service not ready yet ({exc}) ({elapsed:.1f}s elapsed, retry in 3s)...")

        time.sleep(3)

    print(f"\n[FAIL] Service at {base_url} did not respond within {max_wait_s} seconds.")
    sys.exit(1)


def check_endpoints_and_headers(base_url: str, env: str) -> None:
    """Validate core endpoints, static assets, and security headers."""
    print("\n[*] Validating HTTP endpoints and security headers...")

    # 1. Landing Page "/"
    status, headers, body = _make_request(f"{base_url}/")
    if status != 200:
        print(f"    [FAIL] GET / returned {status}")
        sys.exit(1)
    if b"<!DOCTYPE html>" not in body and b"<html" not in body:
        print("    [FAIL] GET / did not return HTML")
        sys.exit(1)
    print("    [PASS] GET / (200 OK, HTML served)")

    # Validate security headers on "/"
    sec_checks = [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
    ]
    for hdr, expected in sec_checks:
        actual = headers.get(hdr)
        if actual != expected:
            print(f"    [FAIL] Header '{hdr}' expected '{expected}', got '{actual}'")
            sys.exit(1)
    print("    [PASS] Security headers present (X-Content-Type-Options, X-Frame-Options, Referrer-Policy)")

    # 2. Planner Page "/plan/"
    status, _, body = _make_request(f"{base_url}/plan/")
    if status != 200:
        print(f"    [FAIL] GET /plan/ returned {status}")
        sys.exit(1)
    print("    [PASS] GET /plan/ (200 OK, HTML served)")

    # 3. Stats Endpoint "/api/stats"
    status, _, body = _make_request(f"{base_url}/api/stats")
    if status != 200:
        print(f"    [FAIL] GET /api/stats returned {status}")
        sys.exit(1)
    stats_data = json.loads(body.decode("utf-8"))
    if "total_trips" not in stats_data:
        print(f"    [FAIL] /api/stats missing 'total_trips' field: {stats_data}")
        sys.exit(1)
    print(f"    [PASS] GET /api/stats (200 OK, total_trips={stats_data.get('total_trips')})")

    # 4. Interactive API Docs "/docs"
    status, _, _ = _make_request(f"{base_url}/docs")
    if status != 200:
        print(f"    [FAIL] GET /docs returned {status}")
        sys.exit(1)
    print("    [PASS] GET /docs (200 OK)")

    # 5. Privacy check: /api/trips must be 404 in production
    status, _, _ = _make_request(f"{base_url}/api/trips")
    if env == "production":
        if status != 404:
            print(f"    [FAIL] Privacy check failed: GET /api/trips returned {status} in production (expected 404)")
            sys.exit(1)
        print("    [PASS] GET /api/trips returns 404 in production (privacy enforcement verified)")
    else:
        print(f"    [INFO] GET /api/trips returned {status} (env={env})")


def run_test_plan(base_url: str) -> None:
    """Submit a small 2-day Bangkok plan and poll until completion."""
    print("\n[*] Running end-to-end plan generation (--plan)...")
    payload = {
        "origin": "Singapore",
        "destination": "Bangkok",
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "travelers": 1,
        "budget_total": 500,
        "budget_currency": "USD",
        "trip_type": "leisure",
        "preferences": ["culture", "temples", "food"],
    }

    submit_url = f"{base_url}/api/plan"
    print(f"    Submitting plan to {submit_url}...")
    status, _, body = _make_request(submit_url, method="POST", data=payload)
    if status != 202:
        print(f"    [FAIL] Plan submission failed with status {status}: {body.decode('utf-8', errors='replace')}")
        sys.exit(1)

    resp_json = json.loads(body.decode("utf-8"))
    job_id = resp_json.get("job_id")
    if not job_id:
        print("    [FAIL] No job_id returned in response")
        sys.exit(1)

    print(f"    [PASS] Job submitted successfully. job_id = {job_id}")

    # Poll status for up to 180 seconds (3 minutes)
    poll_url = f"{base_url}/api/plan/{job_id}"
    start_t = time.time()
    max_wait = 180.0
    last_status = ""

    while time.time() - start_t < max_wait:
        elapsed = time.time() - start_t
        try:
            p_status, _, p_body = _make_request(poll_url, timeout=10.0)
            if p_status == 200:
                job_data = json.loads(p_body.decode("utf-8"))
                current_st = job_data.get("status")
                if current_st != last_status:
                    last_status = current_st
                    print(f"    [{elapsed:5.1f}s] Job status: {current_st}")

                if current_st == "done":
                    total_dur = elapsed
                    result = job_data.get("result") or {}
                    itinerary = result.get("daily_itinerary") or []
                    print(f"\n    [PASS] Job finished successfully in {total_dur:.1f} seconds!")
                    print(f"    Destination: {result.get('destination')}")
                    print(f"    Days planned: {len(itinerary)}")

                    # Validate day blocks
                    if not itinerary:
                        print("    [FAIL] Result contains empty daily_itinerary")
                        sys.exit(1)

                    all_blocks_ok = True
                    for day in itinerary:
                        day_num = day.get("day")
                        has_morning = bool(day.get("morning"))
                        has_afternoon = bool(day.get("afternoon"))
                        has_evening = bool(day.get("evening"))
                        status_str = f"Day {day_num}: morning={'OK' if has_morning else 'MISSING'}, afternoon={'OK' if has_afternoon else 'MISSING'}, evening={'OK' if has_evening else 'MISSING'}"
                        print(f"      - {status_str}")
                        if not (has_morning and has_afternoon and has_evening):
                            all_blocks_ok = False

                    if not all_blocks_ok:
                        print("    [FAIL] Some itinerary days are missing morning/afternoon/evening blocks")
                        sys.exit(1)

                    # Print timing metrics if present
                    timings = job_data.get("result", {}).get("timings") or job_data.get("timings")
                    if timings and isinstance(timings, dict):
                        agents = timings.get("agents") or {}
                        if agents:
                            print("\n    Per-Agent Durations:")
                            for agent_name, agent_info in agents.items():
                                dur = agent_info.get("duration_s", 0)
                                fb = " (fallback)" if agent_info.get("fallback_used") else ""
                                print(f"      * {agent_name:18}: {dur:5.2f}s{fb}")

                    print("\n[SUCCESS] End-to-end plan verification completed successfully.")
                    return

                elif current_st == "failed":
                    err = job_data.get("error")
                    print(f"\n    [FAIL] Plan generation failed: {err}")
                    sys.exit(1)

        except Exception as exc:
            print(f"    [{elapsed:5.1f}s] Polling error: {exc}")

        time.sleep(2.5)

    print(f"\n[FAIL] Plan generation timed out after {max_wait} seconds.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Smoke test script for AI Travel Planner Agent")
    parser.add_argument("url", help="Base URL of the service (e.g. http://localhost:8000 or https://ai-travel-planner.onrender.com)")
    parser.add_argument("--plan", action="store_true", help="Execute an end-to-end 2-day Bangkok plan test")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    print("============================================================")
    print(f"AI Travel Planner Smoke Test -> {base_url}")
    print("============================================================")

    # 1. Wait for health
    health_data = wait_for_health(base_url)
    env = health_data.get("env", "development")

    # 2. Check core endpoints & headers
    check_endpoints_and_headers(base_url, env)

    # 3. Optional end-to-end plan
    if args.plan:
        run_test_plan(base_url)

    print("\n[ALL CHECKS PASSED] Service is healthy and operational.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()

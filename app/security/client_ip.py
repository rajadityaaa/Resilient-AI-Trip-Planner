"""
Client IP extraction helper for reverse proxies and rate limiting.
"""
from __future__ import annotations

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address for rate limiting and auditing.

    When TRUST_PROXY is enabled (e.g. in production behind Render's reverse proxy),
    reads the left-most (originating) IP from the X-Forwarded-For header.

    When TRUST_PROXY is disabled (e.g. default in local development), uses the
    direct socket peer address (request.client.host) to prevent client header spoofing.
    """
    from app.config import get_settings
    settings = get_settings()

    if getattr(settings, "TRUST_PROXY", False):
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can be: "client_ip, proxy1, proxy2"
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"

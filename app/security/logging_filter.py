"""
Logging filter for secret hygiene and data masking.
Automatically scrubs API keys, bearer tokens, and credentials from all log output.
"""
from __future__ import annotations

import logging
import re
from typing import Optional


# Regex patterns matching common secret formats
_SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"sk-or-[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}", re.IGNORECASE),
    re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]{12,})", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*['\"]?)([A-Za-z0-9_\-]{16,})(['\"]?)", re.IGNORECASE),
]


class SecretMaskingFilter(logging.Filter):
    """
    A logging filter that intercepts log records and scrubs any detected API keys
    or authorization header values before writing to console or file.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.mask_secrets(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.mask_secrets(str(a)) if isinstance(a, str) else a for a in record.args)
        return True

    @classmethod
    def mask_secrets(cls, text: str) -> str:
        if not text:
            return ""

        masked = text

        def _sub_secret(match: re.Match) -> str:
            val = match.group(0)
            if val.lower().startswith("bearer "):
                return "Bearer ***"
            elif val.lower().startswith("gsk_"):
                return "gsk_***"
            elif val.lower().startswith("sk-or-"):
                return "sk-or-***"
            elif val.lower().startswith("sk-"):
                return "sk-***"
            return "[MASKED_SECRET]"

        # Mask regex patterns
        for pat in _SECRET_PATTERNS:
            masked = pat.sub(_sub_secret, masked)

        # Also mask actual configured keys if known
        try:
            from app.config import get_settings
            settings = get_settings()
            for key_field in (settings.GROQ_API_KEY, settings.OPENROUTER_API_KEY, settings.FOURSQUARE_API_KEY):
                val = key_field.get_secret_value() if hasattr(key_field, "get_secret_value") else str(key_field)
                val = val.strip()
                if val and len(val) >= 8 and val != "invalid":
                    masked = masked.replace(val, "[MASKED_KEY]")
        except Exception:
            pass

        return masked


def install_secret_masking():
    """Install SecretMaskingFilter on the root logger and all active handlers."""
    filt = SecretMaskingFilter()
    root = logging.getLogger()
    if not any(isinstance(f, SecretMaskingFilter) for f in root.filters):
        root.addFilter(filt)
    for h in root.handlers:
        if not any(isinstance(f, SecretMaskingFilter) for f in h.filters):
            h.addFilter(filt)

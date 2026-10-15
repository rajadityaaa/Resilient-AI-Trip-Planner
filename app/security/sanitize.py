"""
Input sanitization and prompt-injection defense module.
Provides rigorous text and preference sanitization before entering LLM prompts or persistent stores.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Optional

# Patterns for common injection phrases and delimiter escapes
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"(?:\b|^)(system|assistant|user|developer)\s*:\s*", re.IGNORECASE),
    re.compile(r"```[\s\S]*?```", re.IGNORECASE),
    re.compile(r"[`~]{3,}", re.IGNORECASE),
    re.compile(r"<{3,}|>{3,}", re.IGNORECASE),  # Neutralise <<< and >>>
    re.compile(r"<\|.*?\|>", re.IGNORECASE),     # Special tokens like <|im_start|>, <|im_end|>
    re.compile(r"\[/?(inst|sys)\]", re.IGNORECASE), # Llama tokens [INST], [/INST], [SYS]
    re.compile(r"</?[a-zA-Z0-9_\-\s]*(?:instructions?|prompts?|system|context)[^>]*>", re.IGNORECASE), # XML injection tags
]


def sanitize_text(text: Optional[str], max_length: int = 500) -> str:
    """
    Sanitize a single text string:
    - Normalizes unicode (NFKC)
    - Strips non-printable / control characters
    - Collapses repeated whitespace
    - Neutralises prompt injection keywords and role markers
    - Applies a hard maximum length cut
    """
    if not text:
        return ""

    # Normalize unicode to avoid visual spoofing and zero-width tricks
    cleaned = unicodedata.normalize("NFKC", str(text))

    # Strip control characters except standard space
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t"))

    # Neutralise delimiter markers that might clash with prompt wrappers
    cleaned = cleaned.replace("<<<", "").replace(">>>", "")

    # Neutralise known prompt injection phrases
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub("[filtered]", cleaned)

    # Collapse multiple whitespace characters into single space
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Enforce maximum length
    return cleaned[:max_length].strip()


def sanitize_preferences(
    prefs: Optional[List[str]],
    max_items: int = 10,
    max_item_len: int = 50
) -> List[str]:
    """
    Sanitize a list of user preferences:
    - Applies sanitize_text to each element
    - Drops empty or filtered-out elements
    - Deduplicates case-insensitively while preserving order
    - Limits to max_items
    """
    if not prefs or not isinstance(prefs, list):
        return []

    out = []
    seen = set()

    for item in prefs:
        if not isinstance(item, str):
            continue
        cleaned = sanitize_text(item, max_length=max_item_len)
        if not cleaned:
            continue
        lower_key = cleaned.lower()
        if lower_key not in seen:
            seen.add(lower_key)
            out.append(cleaned)
            if len(out) >= max_items:
                break

    return out


def clip_strings(data: Any, max_len: int = 2000, max_length: Optional[int] = None) -> Any:
    """
    Recursively sanitize and clip strings in LLM outputs before storing or rendering.
    Protects against runaway text generation or visual denial of service.
    """
    if max_length is not None:
        max_len = max_length

    if isinstance(data, str):
        # Clip runaway string length
        return data[:max_len]
    elif isinstance(data, dict):
        return {k: clip_strings(v, max_len=max_len) for k, v in data.items()}
    elif isinstance(data, list):
        return [clip_strings(item, max_len=max_len) for item in data]
    return data

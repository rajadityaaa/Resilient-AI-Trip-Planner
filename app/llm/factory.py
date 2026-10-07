import os
import logging
import threading
import time
import json
import re
import requests
from typing import Optional, Callable, Any
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Groq retired llama-3.1-8b-instant and llama-3.3-70b-versatile on 2026-08-16 (they now return 404).
# Replacements recommended by Groq: openai/gpt-oss-20b (fast) and openai/gpt-oss-120b / qwen3.6-27b (smart).
# Preference lists are filtered against what the account actually has (GET /models), so future
# retirements are handled automatically instead of breaking every call.
FAST_MODELS = ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]
SMART_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "llama-3.3-70b-versatile"]

# Fast small model for simple/structured tasks; big model for the harder writing tasks.
FAST_MODEL = FAST_MODELS[0]
SMART_MODEL = SMART_MODELS[0]
GROQ_MODEL_CASCADE = FAST_MODELS + SMART_MODELS

_available_models: Optional[set] = None      # discovered once per process
_dead_models: set = set()                    # models that returned 404/decommissioned this session
_models_lock = threading.Lock()


def _discover_models(api_key: str) -> Optional[set]:
    """Ask Groq which model IDs are live for this key (cached). Returns None if discovery fails."""
    global _available_models
    with _models_lock:
        if _available_models is not None:
            return _available_models
        try:
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {api_key}"}, timeout=6)
            r.raise_for_status()
            _available_models = {m["id"] for m in r.json().get("data", [])}
            logger.info(f"[LLM Factory] Groq models available: {sorted(_available_models)}")
        except Exception as e:
            logger.warning(f"[LLM Factory] Could not list Groq models ({e}); using built-in preferences.")
            _available_models = None
        return _available_models


def _model_params(model: str) -> dict:
    """Extra request params so reasoning models answer quickly and return clean JSON."""
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low", "include_reasoning": False}
    if model.startswith("qwen/"):
        return {"reasoning_format": "hidden"}
    return {}


def _strip_think(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()


# ── Reliability controls ────────────────────────────────────────────────────
# Agents run in parallel; without a limiter they all hit Groq in the same second and get 429s.
# At most LLM_MAX_CONCURRENT calls are in flight; the rest wait their turn (usually < 2s).
LLM_MAX_CONCURRENT = 3
LLM_DEADLINE_S = 22          # one generate() call never takes longer than this (all providers combined)
_llm_slots = threading.Semaphore(LLM_MAX_CONCURRENT)


def _call_groq(prompt: str, system_instruction: Optional[str] = None,
               model_name: str = SMART_MODEL, max_tokens: int = 2048,
               deadline: Optional[float] = None) -> str:
    """
    Call Groq. Tries model_name first, then the remaining live models (same tier first).
    - Skips models that are retired (404 / model_decommissioned) and remembers that for the session.
    - 429: honours a short Retry-After and retries the same model once, otherwise next model.
    - Never exceeds `deadline` (absolute time.time() value).
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if api_key == "invalid":
        raise ValueError("Simulated API Key failure.")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")

    deadline = deadline or (time.time() + LLM_DEADLINE_S)
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    tier = SMART_MODELS if model_name in SMART_MODELS else FAST_MODELS
    other = FAST_MODELS if tier is SMART_MODELS else SMART_MODELS
    candidates = [model_name] + [m for m in tier + other if m != model_name]
    available = _discover_models(api_key)
    if available:
        live = [m for m in candidates if m in available]
        candidates = live or candidates
    candidates = [m for m in candidates if m not in _dead_models] or candidates

    last_err: Any = None
    for m in candidates:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        extras = _model_params(m)
        # reasoning models spend tokens "thinking"; leave headroom so the JSON answer isn't cut off
        budget = max_tokens + (1200 if extras else 0)
        payload = {"model": m, "messages": messages, "temperature": 0.5, "max_tokens": budget, **extras}

        for attempt in range(3):
            remaining = deadline - time.time()
            if remaining < 2:
                raise RuntimeError(f"LLM deadline reached. Last error: {last_err}")
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=min(20, remaining))
                if response.status_code == 401:
                    raise ValueError("Unauthorized: Invalid API Key.")
                if response.status_code in (404, 410) or "decommissioned" in response.text[:300]:
                    _dead_models.add(m)
                    last_err = f"{response.status_code} model unavailable: {m} ({response.text[:120]})"
                    logger.warning(f"[LLM Factory] Groq model '{m}' unavailable - skipping. {response.text[:150]}")
                    break
                if response.status_code == 400 and extras and attempt == 0:
                    logger.warning(f"[LLM Factory] '{m}' rejected reasoning params ({response.text[:120]}); retrying without.")
                    payload = {k: v for k, v in payload.items() if k not in extras}
                    payload["max_tokens"] = max_tokens
                    continue
                if response.status_code == 429:
                    try:
                        wait = float(response.headers.get("retry-after", "99"))
                    except ValueError:
                        wait = 99.0
                    last_err = f"429 rate limit on {m}"
                    logger.warning(f"[LLM Factory] Groq '{m}' rate limited (retry-after={wait}s).")
                    if attempt == 0 and wait <= 4 and deadline - time.time() > wait + 4:
                        time.sleep(wait + 0.2)
                        continue
                    break
                response.raise_for_status()
                content = _strip_think(response.json()["choices"][0]["message"].get("content") or "")
                if not content:
                    last_err = f"empty response from {m} (token budget used up by reasoning?)"
                    logger.warning(f"[LLM Factory] {last_err}")
                    break
                logger.info(f"[LLM Factory] Groq call succeeded with model: {m}")
                return content
            except ValueError:
                raise
            except Exception as e:
                last_err = e
                logger.warning(f"[LLM Factory] Groq model '{m}' failed: {e}")
                break

    raise RuntimeError(f"All Groq models exhausted. Last error: {last_err}")


def _call_openrouter(prompt: str, system_instruction: Optional[str] = None,
                     model_name: str = "openrouter/free", max_tokens: int = 2048,
                     timeout: float = 25) -> str:
    """Call OpenRouter (fallback provider)."""
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable is not set.")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/travel-planner-agent",
        "X-Title": "Travel Planner Agent",
    }
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model_name, "messages": messages, "temperature": 0.5, "max_tokens": max_tokens}

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def get_llm(provider: str = "groq", model: str = FAST_MODEL, max_tokens: int = 1500) -> Callable[[str, Optional[str]], str]:
    """
    Returns generate(prompt, system_instruction=None) -> str.

    Primary: Groq (model, then the other live model). Fallback: OpenRouter.
    Concurrency-limited and deadline-bounded (LLM_DEADLINE_S) so a bad provider can never stall an agent.
    """
    def generate(prompt: str, system_instruction: Optional[str] = None) -> str:
        with _llm_slots:
            deadline = time.time() + LLM_DEADLINE_S      # clock starts once we actually get a slot
            if provider.lower() == "openrouter":
                return _call_openrouter(prompt, system_instruction=system_instruction, max_tokens=max_tokens)
            try:
                return _call_groq(prompt, system_instruction=system_instruction, model_name=model,
                                  max_tokens=max_tokens, deadline=deadline)
            except Exception as primary_err:
                remaining = deadline - time.time()
                logger.warning(f"[LLM Factory] Groq failed ({primary_err}). OpenRouter fallback (remaining {remaining:.0f}s)...")
                if remaining < 5:
                    raise RuntimeError(f"LLM failed on Groq ({primary_err}); no time left for fallback.") from primary_err
                try:
                    return _call_openrouter(prompt, system_instruction=system_instruction,
                                            max_tokens=max_tokens, timeout=min(25, remaining))
                except Exception as fallback_err:
                    raise RuntimeError(
                        f"LLM execution failed on both primary Groq ({primary_err}) and fallback OpenRouter ({fallback_err})."
                    ) from fallback_err

    return generate


def clean_json_response(text: str) -> Any:
    """
    Extract and parse JSON payload from LLM response text, stripping markdown code fences.

    Args:
        text: Raw text string from LLM output.

    Returns:
        Parsed JSON object (dict or list).
    """
    if not text or not text.strip():
        raise ValueError("Empty LLM response text.")

    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()
    else:
        m_arr = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", cleaned)
        if m_arr:
            cleaned = m_arr.group(1).strip()

    return json.loads(cleaned)

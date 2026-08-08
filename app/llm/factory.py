import os
import logging
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

# Groq models to try in order — each has its own per-model quota on the free tier,
# so cycling through them avoids hitting rate limits during multi-agent runs.
GROQ_MODEL_CASCADE = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

# Minimum delay between consecutive Groq calls (seconds) to avoid rate limits
_last_groq_call = 0.0


def _call_groq(prompt: str, system_instruction: Optional[str] = None, model_name: str = "llama-3.3-70b-versatile") -> str:
    """
    Call Groq API using requests HTTP POST.
    Tries the specified model first, then cascades through GROQ_MODEL_CASCADE on failure.
    Enforces a 2-second minimum gap between calls to stay within rate limits.
    """
    global _last_groq_call

    api_key = os.getenv("GROQ_API_KEY", "")
    # Check if key is set to 'invalid' for testing fallbacks
    if api_key == "invalid" or os.getenv("GROQ_API_KEY", "") == "invalid":
        raise ValueError("Simulated API Key failure.")
        
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")

    # Rate-limit: enforce minimum 2-second gap between calls
    elapsed = time.time() - _last_groq_call
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Build model list: start with requested, then cascade
    models_to_try = [model_name] + [m for m in GROQ_MODEL_CASCADE if m != model_name]
    last_err = None

    for m in models_to_try:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": m,
            "messages": messages,
            "temperature": 0.7,
        }

        is_401 = False
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 401:
                is_401 = True
            elif response.status_code == 429:
                err_data = response.json()
                logger.warning(f"[LLM Factory] Groq model '{m}' rate limited: {err_data}. Sleeping 5s before next attempt...")
                time.sleep(5.0)
                continue
            else:
                response.raise_for_status()
                data = response.json()
                _last_groq_call = time.time()
                logger.info(f"[LLM Factory] Groq call succeeded with model: {m}")
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            logger.warning(f"[LLM Factory] Groq model '{m}' failed: {e}. Sleeping 2s...")
            time.sleep(2.0)
            continue

        if is_401:
            raise ValueError("Unauthorized: Invalid API Key.")

    raise RuntimeError(f"All Groq models exhausted. Last error: {last_err}")


def _call_openrouter(
    prompt: str,
    system_instruction: Optional[str] = None,
    model_name: str = "openrouter/free"
) -> str:
    """
    Call OpenRouter API using requests HTTP POST.
    """
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

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.7,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def get_llm(provider: str = "groq") -> Callable[[str, Optional[str]], str]:
    """
    Factory function returning an LLM generator function with retry-fallback capability.

    Primary Provider: Groq (cascades through 4 models with separate quotas)
    Fallback Provider: OpenRouter free model (e.g. openrouter/free)

    If the primary call raises an exception (rate limit, quota, network timeout),
    it automatically retries once against the fallback provider.

    Args:
        provider: Preferred provider ('groq' or 'openrouter'). Default is 'groq'.

    Returns:
        A callable generate(prompt: str, system_instruction: Optional[str] = None) -> str
    """
    def generate(prompt: str, system_instruction: Optional[str] = None) -> str:
        selected_provider = provider.lower()
        if selected_provider == "groq":
            selected_provider = "groq"

        if selected_provider == "openrouter":
            return _call_openrouter(prompt, system_instruction=system_instruction)

        # Primary: Groq (with model cascade)
        try:
            return _call_groq(prompt, system_instruction=system_instruction)
        except Exception as primary_err:
            logger.warning(
                f"[LLM Factory] Primary Groq call failed ({primary_err}). Automatically retrying with OpenRouter fallback..."
            )
            try:
                return _call_openrouter(prompt, system_instruction=system_instruction)
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

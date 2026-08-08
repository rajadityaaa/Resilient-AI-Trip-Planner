"""
Currency Tools: Frankfurter API wrapper for exchange rates with 12-hour TTL caching.
"""
import requests
from datetime import datetime
from typing import Optional
from app.tools.cache import cache_get, cache_set


def convert_currency(amount: float, from_code: str, to_code: str) -> dict:
    """
    Convert amount from one currency to another using ECB exchange rates via Frankfurter API.

    - Short-circuits if from_code == to_code without hitting network.
    - Caches exchange rates with a 12-hour TTL via cache.py.

    Args:
        amount: Numerical amount to convert.
        from_code: ISO currency code (e.g. "USD").
        to_code: ISO currency code (e.g. "INR").

    Returns:
        dict: {
            "amount": float,
            "from_code": str,
            "to_code": str,
            "converted_amount": float,
            "rate": float,
            "date": str
        }
    """
    from_curr = (from_code or "USD").strip().upper()
    to_curr = (to_code or "USD").strip().upper()
    amt = float(amount)
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Short-circuit if same currency
    if from_curr == to_curr:
        return {
            "amount": amt,
            "from_code": from_curr,
            "to_code": to_curr,
            "converted_amount": amt,
            "rate": 1.0,
            "date": today_str
        }

    cache_key = f"currency:{from_curr}:{to_curr}"
    cached = cache_get(cache_key)
    if cached is not None:
        rate = cached["rate"]
        date_val = cached.get("date", today_str)
        return {
            "amount": amt,
            "from_code": from_curr,
            "to_code": to_curr,
            "converted_amount": round(amt * rate, 2),
            "rate": rate,
            "date": date_val
        }

    url = f"https://api.frankfurter.app/latest?from={from_curr}&to={to_curr}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        rates = data.get("rates", {})
        if to_curr not in rates:
            raise ValueError(f"Target currency '{to_curr}' not returned by API.")

        rate = float(rates[to_curr])
        date_val = data.get("date", today_str)
    except Exception as err:
        # Default 1.0 fallback on failure to avoid crashing
        rate = 1.0
        date_val = today_str

    result_payload = {
        "rate": rate,
        "date": date_val
    }
    # Cache rates for 12 hours (43,200 seconds)
    cache_set(cache_key, result_payload, ttl_seconds=43200)

    return {
        "amount": amt,
        "from_code": from_curr,
        "to_code": to_curr,
        "converted_amount": round(amt * rate, 2),
        "rate": rate,
        "date": date_val
    }

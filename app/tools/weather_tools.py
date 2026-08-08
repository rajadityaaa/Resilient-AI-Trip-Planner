"""
Weather Tools: Open-Meteo API wrapper for forecast and climate normals.
"""
import requests
from datetime import datetime, timedelta
from typing import Optional
from app.tools.cache import cache_get, cache_set


def _map_wmo_code(code: Optional[int]) -> str:
    """Map WMO weather code to human-readable weather condition string."""
    if code is None:
        return "Unknown"
    code_map = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return code_map.get(code, "Partly cloudy")


def get_forecast(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """
    Retrieve daily weather forecast or historical climate estimate for a location and date range.

    - Uses Open-Meteo Forecast API (https://api.open-meteo.com/v1/forecast) for dates within ~16 days.
    - Automatically falls back to Climate Normals / Archive API for dates > 16 days out.
    - Sets is_estimate: True for climate estimate results.
    - Caches results with a 6-hour TTL via cache.py.

    Args:
        lat: Latitude coordinate.
        lon: Longitude coordinate.
        start_date: ISO date string (YYYY-MM-DD).
        end_date: ISO date string (YYYY-MM-DD).

    Returns:
        dict: {
            "daily": [
                {
                    "date": str,
                    "temp_max": float,
                    "temp_min": float,
                    "precipitation_mm": float,
                    "condition": str
                }
            ],
            "is_estimate": bool
        }
    """
    cache_key = f"weather:{lat:.4f}:{lon:.4f}:{start_date}:{end_date}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    today = datetime.now().date()
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        start_dt = today

    days_ahead = (start_dt - today).days
    is_far_future = days_ahead > 16

    result = None

    if not is_far_future:
        # Standard forecast request
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "timezone": "auto"
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("daily", {})
                times = data.get("time", [])
                t_max = data.get("temperature_2m_max", [])
                t_min = data.get("temperature_2m_min", [])
                precip = data.get("precipitation_sum", [])
                codes = data.get("weathercode", [])

                daily_list = []
                for i, d_str in enumerate(times):
                    daily_list.append({
                        "date": d_str,
                        "temp_max": float(t_max[i]) if i < len(t_max) and t_max[i] is not None else 0.0,
                        "temp_min": float(t_min[i]) if i < len(t_min) and t_min[i] is not None else 0.0,
                        "precipitation_mm": float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
                        "condition": _map_wmo_code(codes[i] if i < len(codes) else None)
                    })

                result = {
                    "daily": daily_list,
                    "is_estimate": False
                }
        except Exception:
            result = None

    # Fallback to historical climate estimate if start_date is > 16 days out or forecast call failed
    if result is None:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            end_dt = start_dt + timedelta(days=3)

        # Estimate using past year archive dates
        past_year = today.year - 1
        try:
            past_start = start_dt.replace(year=past_year)
            past_end = end_dt.replace(year=past_year)
        except ValueError: # handle leap day Feb 29
            past_start = start_dt + timedelta(days=-365)
            past_end = end_dt + timedelta(days=-365)

        archive_url = "https://archive-api.open-meteo.com/v1/archive"
        archive_params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": past_start.strftime("%Y-%m-%d"),
            "end_date": past_end.strftime("%Y-%m-%d"),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "timezone": "auto"
        }
        try:
            resp = requests.get(archive_url, params=archive_params, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("daily", {})
            times = data.get("time", [])
            t_max = data.get("temperature_2m_max", [])
            t_min = data.get("temperature_2m_min", [])
            precip = data.get("precipitation_sum", [])
            codes = data.get("weathercode", [])

            daily_list = []
            for i, _ in enumerate(times):
                # Map back date string to requested target dates
                target_date = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
                daily_list.append({
                    "date": target_date,
                    "temp_max": float(t_max[i]) if i < len(t_max) and t_max[i] is not None else 0.0,
                    "temp_min": float(t_min[i]) if i < len(t_min) and t_min[i] is not None else 0.0,
                    "precipitation_mm": float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
                    "condition": _map_wmo_code(codes[i] if i < len(codes) else None)
                })

            result = {
                "daily": daily_list,
                "is_estimate": True
            }
        except Exception:
            # Fallback to climate API endpoint if archive request fails
            climate_url = "https://climate-api.open-meteo.com/v1/climate"
            climate_params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "models": "CMCC_CM2_VHR4",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            }
            resp = requests.get(climate_url, params=climate_params, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("daily", {})
            times = data.get("time", [])
            t_max = data.get("temperature_2m_max", [])
            t_min = data.get("temperature_2m_min", [])
            precip = data.get("precipitation_sum", [])

            daily_list = []
            for i, d_str in enumerate(times):
                daily_list.append({
                    "date": d_str,
                    "temp_max": float(t_max[i]) if i < len(t_max) and t_max[i] is not None else 0.0,
                    "temp_min": float(t_min[i]) if i < len(t_min) and t_min[i] is not None else 0.0,
                    "precipitation_mm": float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
                    "condition": "Typical seasonal climate"
                })

            result = {
                "daily": daily_list,
                "is_estimate": True
            }

    # Cache result with a 6-hour TTL (21,600 seconds)
    cache_set(cache_key, result, ttl_seconds=6 * 3600)
    return result

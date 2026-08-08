"""
Prompt template for Packing Agent.
Instructs LLM to generate categorized packing list.
"""
import json


def build_packing_prompt(weather_summary: str, trip_type: str, preferences: list[str]) -> str:
    prefs_str = ", ".join(preferences) if preferences else "general"
    return f"""You are a travel preparation expert.
Generate a comprehensive packing checklist for a {trip_type} trip with preferences [{prefs_str}].
Expected Weather: {weather_summary}

Respond ONLY in valid JSON matching a flat array of item strings with no markdown fences, no code blocks, and no preamble text:
[
  "Light breathable cotton clothing",
  "Comfortable walking shoes",
  "Universal power adapter",
  "Sunscreen & sunglasses",
  "Passport and visa documents",
  "First aid kit & basic medications"
]
"""

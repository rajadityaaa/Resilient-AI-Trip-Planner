"""
Prompt template for Restaurant Agent.
Instructs LLM to rank and flag restaurants matching cuisine/dietary needs.
"""
import json


def build_restaurant_ranking_prompt(preferences: list[str], raw_restaurants: list[dict]) -> str:
    prefs_str = ", ".join(preferences) if preferences else "general dining"
    places_json = json.dumps(raw_restaurants[:20], indent=2)

    return f"""You are a culinary travel expert.
User Preferences & Dietary Needs: {prefs_str}

Below is a list of candidate restaurants retrieved from OpenStreetMap:
{places_json}

Filter and rank these restaurants based on how well they match the user's culinary and dietary preferences.
Select up to 10 top dining spots.

Respond ONLY in valid JSON matching this exact structure with no markdown fences, no code blocks, and no preamble text:
[
  {{
    "name": "Restaurant Name",
    "category": "Restaurant",
    "lat": 26.920,
    "lon": 75.823,
    "match_reason": "Explanation of why this place matches preferences."
  }}
]
"""

"""
Prompt template for Attraction Agent.
Instructs LLM to filter and rank raw OSM attractions against user preferences.
"""
import json


def build_attraction_ranking_prompt(preferences: list[str], raw_attractions: list[dict]) -> str:
    prefs_str = ", ".join(preferences) if preferences else "general sightseeing"
    places_json = json.dumps(
        [{"name": p.get("name"), "category": p.get("category"), "lat": round(p.get("lat", 0), 5), "lon": round(p.get("lon", 0), 5),
           **({"cuisine": p["tags"]["cuisine"]} if p.get("tags", {}).get("cuisine") else {})} for p in raw_attractions[:20]]
    )

    return f"""You are a travel curation expert.
User Preferences: {prefs_str}

Below is a raw list of candidate attractions retrieved from OpenStreetMap:
{places_json}

Filter and rank these attractions according to how well they match the user's preferences.
Select up to 10 top attractions.

Respond ONLY in valid JSON matching this exact structure with no markdown fences, no code blocks, and no preamble text:
[
  {{
    "name": "Attraction Name",
    "category": "Category",
    "lat": 26.912,
    "lon": 75.819,
    "match_reason": "Explanation of why this matches the user preferences."
  }}
]
"""
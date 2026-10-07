"""
Fallback prompt used ONLY when OpenStreetMap returns nothing for a destination.
Asks the LLM for well-known, real places (clearly flagged as AI-suggested in the app).
"""


def build_place_fallback_prompt(kind: str, destination: str, preferences: list, center_lat: float, center_lon: float) -> str:
    prefs = ", ".join(preferences) if preferences else "general sightseeing"
    if kind == "attractions":
        what = "famous, real tourist attractions and landmarks"
        cat = "Attraction"
    else:
        what = "well-known, real restaurants, cafes or food streets/markets"
        cat = "Restaurant"
    return f"""List 10 {what} in {destination} that a visitor interested in: {prefs} would enjoy.
Only include places you are confident really exist. Use approximate GPS coordinates (the city centre is near lat {center_lat:.3f}, lon {center_lon:.3f}).

Respond ONLY with valid JSON, no markdown:
[{{"name": "Place Name", "category": "{cat}", "lat": {center_lat:.3f}, "lon": {center_lon:.3f}, "match_reason": "one short sentence"}}]"""

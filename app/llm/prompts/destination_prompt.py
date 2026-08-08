"""
Prompt template for Destination Agent.
Instructs LLM to return strictly valid JSON for 3-5 candidate destinations.
"""

def build_destination_prompt(trip_type: str, preferences: list[str], origin: str, budget_total: float, budget_currency: str) -> str:
    prefs_str = ", ".join(preferences) if preferences else "general sight-seeing"
    return f"""You are a world-class travel planner assistant.
The user wants to plan a trip with the following details:
- Departure Origin: {origin}
- Total Budget: {budget_currency} {budget_total:.2f}
- Trip Type: {trip_type}
- Preferences & Interests: {prefs_str}

Suggest 3 to 5 candidate destinations that are realistic and reachable from {origin} within a budget of {budget_currency} {budget_total:.2f}.

Respond ONLY in valid JSON matching this exact structure with no markdown fences, no code blocks, and no preamble text:
[
  {{
    "destination": "City, Country",
    "description": "Short 1-2 sentence description of why this destination fits.",
    "estimated_cost_usd": 1200.0,
    "reasons": ["Reason 1", "Reason 2"]
  }}
]
"""

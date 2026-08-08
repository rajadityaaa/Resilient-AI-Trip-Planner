"""
Prompt template for Hotel Agent fallback.
Instructs LLM to generate mock hotel options for unlisted destinations.
"""

def build_hotel_fallback_prompt(destination: str, budget_total: float, budget_currency: str, trip_type: str) -> str:
    return f"""You are a hotel booking concierge.
The destination "{destination}" does not have pre-indexed mock hotels in our local database.
Generate 3 to 5 realistic mock hotel options suitable for a {trip_type} trip with a total budget of {budget_currency} {budget_total:.2f}.

Respond ONLY in valid JSON matching this exact structure with no markdown fences, no code blocks, and no preamble text:
[
  {{
    "name": "Hotel Name",
    "city": "{destination}",
    "star_rating": 4.5,
    "price_per_night_usd": 120.0,
    "category": "mid-range",
    "amenities": ["Free WiFi", "AC", "Breakfast Included"],
    "address": "12 Central Street, {destination}"
  }}
]
"""

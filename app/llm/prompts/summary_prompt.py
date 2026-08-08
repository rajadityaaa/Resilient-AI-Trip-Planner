"""
Prompt template for Summary Agent.
Instructs LLM to synthesize all agent outputs into a coherent day-by-day itinerary.
"""
import json


def build_summary_prompt(state: dict) -> str:
    destination = state.get("destination", "Unknown")
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    trip_type = state.get("trip_type", "leisure")
    travelers = state.get("travelers", 1)
    preferences = ", ".join(state.get("preferences", [])) or "general sightseeing"

    # Weather summary
    weather = state.get("weather")
    weather_block = "Weather data unavailable."
    if weather and isinstance(weather, dict):
        daily_w = weather.get("daily", [])
        if daily_w:
            lines = []
            for d in daily_w[:7]:
                lines.append(f"  {d.get('date','?')}: {d.get('condition','?')}, {d.get('temp_min',0):.0f}-{d.get('temp_max',0):.0f}°C, precip {d.get('precipitation_mm',0):.1f}mm")
            weather_block = "\n".join(lines)
            if weather.get("is_estimate"):
                weather_block += "\n  (Note: this is a climate estimate, not a live forecast)"

    # Attractions
    attractions = state.get("attractions", [])
    attr_block = "Attractions unavailable."
    if attractions:
        attr_names = [a.get("name", "?") for a in attractions[:10]]
        attr_block = json.dumps(attr_names, indent=2)

    # Restaurants
    restaurants = state.get("restaurants", [])
    rest_block = "Restaurant data unavailable."
    if restaurants:
        rest_names = [r.get("name", "?") for r in restaurants[:10]]
        rest_block = json.dumps(rest_names, indent=2)

    # Hotels
    hotels = state.get("hotels", [])
    hotel_block = "Hotel data unavailable."
    if hotels:
        hotel_summaries = [f"{h.get('name','?')} (${h.get('price_per_night_usd', h.get('price_per_night', '?'))}/night)" for h in hotels[:5]]
        hotel_block = ", ".join(hotel_summaries)

    # Budget
    budget = state.get("budget_breakdown")
    budget_block = "Budget breakdown unavailable."
    if budget and isinstance(budget, dict):
        budget_block = json.dumps(budget, indent=2)

    # Transport
    transport = state.get("transport_guide")
    transport_block = "Transport guide unavailable."
    if transport and isinstance(transport, dict):
        transport_block = json.dumps(transport, indent=2)

    # Packing
    packing = state.get("packing_list", [])
    packing_block = "Packing list unavailable."
    if packing:
        packing_block = ", ".join(packing[:10])

    # Currency
    currency = state.get("currency_info")
    currency_block = "Currency info unavailable."
    if currency and isinstance(currency, dict):
        currency_block = f"Local currency: {currency.get('local_currency','?')}, Rate: {currency.get('exchange_rate','?')}, Tips: {currency.get('cash_tips','')}"

    # Errors
    errors = state.get("errors", [])
    error_block = ""
    if errors:
        err_lines = [f"  - {e.get('agent','?')}: {e.get('message','?')}" for e in errors]
        error_block = f"\nNOTE — The following data sources had errors (handle gracefully with 'unavailable' placeholders):\n" + "\n".join(err_lines)

    # Dynamic instructions if collections are empty/missing
    missing_instructions = []
    if not attractions:
        missing_instructions.append("No attraction data is available for this trip — do NOT invent, assume, or reference any named attractions, landmarks, or sites. Structure morning/afternoon blocks around restaurants, hotel-based activities, or general free time instead, and clearly state in the notes field that attraction data was unavailable for this section.")
    if not restaurants:
        missing_instructions.append("No restaurant data is available for this trip — do NOT invent, assume, or reference any named restaurants, cafes, or eateries. Structure morning/afternoon/evening blocks around attractions, hotel-based activities, or general free time instead, and clearly state in the notes field that restaurant data was unavailable for this section.")
    if not hotels:
        missing_instructions.append("No hotel data is available for this trip — do NOT invent, assume, or reference any named hotels or resorts. Reference lodging in general terms or state that lodging details are unavailable.")

    missing_block = ""
    if missing_instructions:
        missing_block = "\n" + "\n".join(f"{i+6}. {inst}" for i, inst in enumerate(missing_instructions))

    return f"""You are a premium travel itinerary creator.
Synthesize the following trip data into a coherent day-by-day itinerary.

TRIP DETAILS:
- Destination: {destination}
- Dates: {start_date} to {end_date}
- Trip Type: {trip_type}
- Travelers: {travelers}
- Preferences: {preferences}

WEATHER:
{weather_block}

ATTRACTIONS:
{attr_block}

RESTAURANTS:
{rest_block}

HOTELS:
{hotel_block}

BUDGET:
{budget_block}

TRANSPORT:
{transport_block}

PACKING HIGHLIGHTS:
{packing_block}

CURRENCY:
{currency_block}
{error_block}

INSTRUCTIONS:
1. Create a day-by-day itinerary with morning, afternoon, and evening activities.
2. Reference SPECIFIC attractions and restaurants from the lists above. You are given a closed list of real attractions and a closed list of real restaurants below. You MUST ONLY reference places by name that appear EXACTLY in these two lists. Do NOT mention any other named place, landmark, restaurant, or attraction, even extremely famous ones (e.g. Eiffel Tower, Louvre), unless it is literally present in the provided lists. If the provided lists don't have enough distinct places to fill every day without repetition, it is acceptable to repeat a place across days or use generic activities ('free time to explore the neighborhood', 'shopping at a local market') instead of inventing a new named place.
3. Add weather-appropriate notes (e.g. "carry umbrella" if rain is forecast that day, reference packing items).
4. If any data section above says "unavailable", mark that section as "Data unavailable — please check manually" in the itinerary. Do NOT invent data.
5. Also produce a short trip_title and overview_paragraph.{missing_block}

Respond ONLY in valid JSON matching this exact structure with no markdown fences, no code blocks, and no preamble text:
{{
  "trip_title": "A catchy title for this trip",
  "overview_paragraph": "A 2-3 sentence overview of the trip plan.",
  "daily_itinerary": [
    {{
      "day": 1,
      "date": "{start_date}",
      "morning": "Morning activity description referencing specific places.",
      "afternoon": "Afternoon activity description.",
      "evening": "Evening activity description.",
      "notes": "Weather note, packing reminder, or travel tip for this day."
    }}
  ]
}}
"""

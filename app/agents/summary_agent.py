"""
Summary Agent: Merges all specialist agent outputs into a coherent day-by-day itinerary.
ALWAYS runs even if upstream agents logged errors — uses "unavailable" placeholders for missing data.
Any field that receives a placeholder is explicitly logged to state["errors"] so the CLI
harness and Streamlit UI can surface data quality honestly.
"""
import json
import re
from datetime import datetime, timedelta
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.summary_prompt import build_summary_prompt

# Sentinel strings that the LLM is instructed to use (from summary_prompt.py)
# when a data section was unavailable. We detect these to log degradation.
_PLACEHOLDER_MARKERS = [
    "data unavailable",
    "please check manually",
    "unavailable —",
    "unavailable -",
    "information not available",
]

_ITINERARY_FIELDS = ("morning", "afternoon", "evening", "notes")


def _is_placeholder(text: str) -> bool:
    """Return True if text contains a known 'unavailable' placeholder marker."""
    if not text:
        return True
    text_lower = text.lower()
    return any(marker in text_lower for marker in _PLACEHOLDER_MARKERS)


def _audit_itinerary(itinerary: list[dict], errors: list[dict]) -> None:
    """
    Walk every day/field in the generated itinerary and append an error entry
    for each field that is missing, empty, or contains a placeholder string.
    """
    for day_entry in itinerary:
        day_num = day_entry.get("day", "?")
        day_date = day_entry.get("date", "?")

        for field in _ITINERARY_FIELDS:
            value = day_entry.get(field, "")
            if _is_placeholder(value):
                errors.append({
                    "agent": "summary_agent",
                    "message": (
                        f"Day {day_num} ({day_date}) {field}: "
                        f"LLM response was incomplete or unavailable — placeholder inserted."
                    )
                })


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


def _build_fallback_itinerary(state: TripState) -> list[dict]:
    """Build minimal fallback itinerary from available data."""
    try:
        start = datetime.strptime(state.get("start_date", "2026-09-01"), "%Y-%m-%d")
        end = datetime.strptime(state.get("end_date", "2026-09-05"), "%Y-%m-%d")
        num_days = max(1, (end - start).days)
    except Exception:
        start = datetime.now()
        num_days = 3

    dest = state.get("destination", "your destination")
    attractions = state.get("attractions", [])
    restaurants = state.get("restaurants", [])

    fallback = []
    for i in range(num_days):
        day_date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        attr_name = attractions[i % len(attractions)].get("name", "local sight") if attractions else "Explore the city"
        rest_name = restaurants[i % len(restaurants)].get("name", "local restaurant") if restaurants else "Try local cuisine"

        entry = {
            "day": i + 1,
            "date": day_date,
            "morning": f"Visit {attr_name}" if i < len(attractions) else f"Free morning to explore {dest}",
            "afternoon": f"Lunch at {rest_name}, then explore nearby areas",
            "evening": "Dinner and evening leisure at hotel",
            "notes": "Check weather forecast and dress accordingly."
        }
        fallback.append(entry)

    if fallback:
        fallback[0]["_trip_title"] = f"Trip to {dest}"
        fallback[0]["_overview"] = (
            f"A {num_days}-day itinerary for {dest}. "
            "Some sections may be incomplete due to data retrieval issues."
        )

    return fallback


def _extract_proper_nouns(text: str) -> list[str]:
    # Match sequences of capitalized words, allowing spaces, hyphens, and apostrophes
    candidates = re.findall(r'\b[A-Z][a-zA-Z0-9\'-]*(?:\s+[A-Z][a-zA-Z0-9\'-]*)*\b', text)
    
    ignore = {
        "the", "a", "an", "in", "on", "at", "by", "for", "with", "about", "from", "to", "and", "or", "of", "as", "but", "so", "if",
        "morning", "afternoon", "evening", "night", "day", "notes", "tip", "weather", "temperature",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
        "jaipur", "paris", "bangkok", "delhi", "tokyo", "india", "france", "thailand", "japan",
        "you", "we", "i", "your", "our", "my", "he", "she", "they", "it", "his", "her", "their", "them", "us",
        "local", "rooftop", "cafe", "restaurant", "hotel", "museum", "palace", "temple", "street", "market", "city", "town", "station", "airport", "expeditionary", "force", "bazaar", "bazaars", "park", "garden", "gardens", "shopping", "mall",
        "metro", "skytrain", "bts", "mrt", "taxi", "rideshare", "grab", "uber", "ola", "tuk-tuk", "tuk", "tuks", "rail", "link", "arl", "tourist", "card", "smart", "pass",
        "afterwards", "afterward", "later", "then", "after", "also", "here", "there", "first", "second", "third", "finally", "next", "free", "have", "enjoying", "savoring", "dining", "grab", "find", "get", "make", "make sure", "be sure", "don't",
        "check-out", "check-in", "relaxation", "activities", "activity", "data", "information",
        "rabbit", "rabbit card", "thb", "usd", "inr", "eur", "gbp", "baht", "rupee", "dollar", "euro", "pound",
        
        # Sentence openers / Verbs / Imperatives
        "agree", "visit", "explore", "bring", "wear", "enjoy", "consider", "take", "head", "try", "don't", "dont", "make", 
        "grab", "find", "get", "spend", "stop", "go", "pack", "carry", "check", "arrive", "depart", "return", "stroll", "walk", 
        "savor", "dine", "lunch", "breakfast", "dinner", "start", "end", "choose", "pick", "select", "purchase", "buy", "use", 
        "insist", "ask", "request", "tell", "say", "note", "remember", "keep", "stay", "avoid", "watch", "be", "prepare", "allow", 
        "plan", "book", "reserve", "transfer", "heading", "shopping", "exploring", "dining", "relaxing", "later",
        
        # Cuisines / Nationalities / Regions
        "chinese", "thai", "french", "indian", "italian", "japanese", "mexican", "vietnamese", "korean", "greek", "turkish", 
        "spanish", "british", "english", "american", "canadian", "australian", "german", "asian", "european", "african", 
        "latin", "mediterranean", "oriental", "middle", "east", "eastern", "west", "western", "north", "northern", "south", "southern",
        "cuisine", "style", "flavor", "flavors", "dishes", "dish", "veg", "vegan", "vegetarian"
    }

    start_verbs = {
        "agree", "visit", "explore", "bring", "wear", "enjoy", "consider", "take", "head", "try", "don't", "dont", "make", 
        "grab", "find", "get", "spend", "stop", "go", "pack", "carry", "check", "arrive", "depart", "return", "stroll", "walk", 
        "savor", "dine", "lunch", "breakfast", "dinner", "start", "end", "choose", "pick", "select", "purchase", "buy", "use", 
        "insist", "ask", "request", "tell", "say", "note", "remember", "keep", "stay", "avoid", "watch", "be", "prepare", "allow", 
        "plan", "book", "reserve", "transfer", "afterwards", "afterward", "later", "then", "after", "also", "here", "there", 
        "first", "second", "third", "finally", "next", "free", "have", "enjoying", "savoring", "dining"
    }
    
    proper_nouns = []
    for cand in candidates:
        cand_clean = cand.strip()
        if not cand_clean:
            continue
            
        # Strip trailing possessives ('s or s')
        cand_clean = re.sub(r"'s$", "", cand_clean, flags=re.IGNORECASE)
        cand_clean = re.sub(r"'$", "", cand_clean)
        
        # Strip standard leading action verbs/connectors if it's a multi-word phrase
        words = re.split(r'[-\s]', cand_clean)
        if len(words) > 1:
            first_word_lower = words[0].lower()
            if first_word_lower in start_verbs:
                cand_clean = " ".join(words[1:])
                words = re.split(r'[-\s]', cand_clean)

        # Re-check candidate after cleaning
        if not cand_clean or len(cand_clean) <= 2:
            continue

        if len(words) == 1:
            if cand_clean.lower() in ignore:
                continue
        else:
            if all(w.lower() in ignore for w in words):
                continue
        
        # Strip trailing punctuation just in case
        cand_clean = re.sub(r'[.,;:!?]$', '', cand_clean)
        proper_nouns.append(cand_clean)
        
    return proper_nouns


def _validate_itinerary_names(state: TripState) -> None:
    """
    Validate that all referenced place names in the generated itinerary
    exist in the source attractions, restaurants, or hotels lists.
    """
    # 1. Collect all valid source names
    source_names = []
    for item in (state.get("attractions", []) or []):
        if item.get("name"):
            source_names.append(item["name"].lower())
    for item in (state.get("restaurants", []) or []):
        if item.get("name"):
            source_names.append(item["name"].lower())
    for item in (state.get("hotels", []) or []):
        if item.get("name"):
            source_names.append(item["name"].lower())

    if not source_names:
        return

    # 2. Extract and cross-check all proper nouns from itinerary fields
    invented_places = set()
    for day in (state.get("daily_itinerary", []) or []):
        for field in ["morning", "afternoon", "evening"]:
            text = day.get(field, "")
            if not text:
                continue
                
            candidates = _extract_proper_nouns(text)
            for cand in candidates:
                cand_lower = cand.lower()
                
                # Check for substring match in source names
                matched = False
                for sname in source_names:
                    if cand_lower in sname or sname in cand_lower:
                        matched = True
                        break
                
                if not matched:
                    invented_places.add(cand)

    # 3. Log any discrepancies to state["errors"]
    if invented_places:
        places_str = ", ".join(sorted(invented_places))
        state["errors"].append({
            "agent": "summary_agent",
            "message": f"summary_agent: itinerary referenced possibly invented place names: [{places_str}]"
        })


async def build_summary(state: TripState) -> TripState:
    """
    Synthesize every populated field in state into a day-by-day itinerary.
    Handles missing/empty sections gracefully with labeled "unavailable" placeholders.
    Any field that falls back to a placeholder is appended to state["errors"].
    """
    _init_errors(state)

    # Check for empty attractions, restaurants, and hotels up front
    attractions = state.get("attractions")
    if not attractions:
        state["errors"].append({
            "agent": "summary_agent",
            "message": "summary_agent: no attraction data available, itinerary built without attraction recommendations"
        })

    restaurants = state.get("restaurants")
    if not restaurants:
        state["errors"].append({
            "agent": "summary_agent",
            "message": "summary_agent: no restaurant data available, itinerary built without restaurant recommendations"
        })

    hotels = state.get("hotels")
    if not hotels:
        state["errors"].append({
            "agent": "summary_agent",
            "message": "summary_agent: no hotel data available, itinerary built without hotel recommendations"
        })

    try:
        llm = get_llm()
        prompt = build_summary_prompt(state)
        resp_text = llm(prompt)
        
        try:
            parsed = clean_json_response(resp_text)
        except json.JSONDecodeError:
            # Retry once with stricter formatting instructions
            retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
            resp_text = llm(prompt + retry_instruction)
            try:
                parsed = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Log a non-technical error and build fallback itinerary
                state["errors"].append({
                    "agent": "summary_agent",
                    "message": "summary_agent: LLM response could not be parsed after retry, using fallback itinerary"
                })
                fallback = _build_fallback_itinerary(state)
                state["daily_itinerary"] = fallback
                _audit_itinerary(fallback, state["errors"])
                return state

        if isinstance(parsed, dict):
            state["daily_itinerary"] = parsed.get("daily_itinerary", [])
            # Store trip title and overview in daily_itinerary metadata
            if state["daily_itinerary"] and len(state["daily_itinerary"]) > 0:
                # Attach trip metadata to the first entry for easy access
                state["daily_itinerary"][0]["_trip_title"] = parsed.get("trip_title", "Your Trip Itinerary")
                state["daily_itinerary"][0]["_overview"] = parsed.get("overview_paragraph", "")

            # Audit every day/field for placeholders and log any degradations
            _audit_itinerary(state["daily_itinerary"], state["errors"])
        else:
            raise ValueError("Summary response is not a dict.")

    except Exception as err:
        state["errors"].append({"agent": "summary_agent", "message": str(err)})
        fallback = _build_fallback_itinerary(state)
        state["daily_itinerary"] = fallback
        _audit_itinerary(fallback, state["errors"])

    # Python-side validation of referenced place names
    _validate_itinerary_names(state)

    return state

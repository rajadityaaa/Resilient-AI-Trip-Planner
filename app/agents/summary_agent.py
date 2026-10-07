"""
Summary Agent: Merges all specialist agent outputs into a coherent day-by-day itinerary.
ALWAYS runs even if upstream agents logged errors — uses "unavailable" placeholders for missing data.
Any field that receives a placeholder is explicitly logged to state["errors"] so the CLI
harness and Streamlit UI can surface data quality honestly.
"""
import asyncio
import json
import re
from typing import Optional
from datetime import datetime, timedelta
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response, SMART_MODEL
from app.agents import progress
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


# ── Per-day parallel generation ─────────────────────────────────────────────
# Instead of ONE huge LLM call that must return the whole trip as perfect JSON (slow, and weak
# fallback models tend to return only the 1-day example), we generate each day with its own
# small call, all in parallel. Places are assigned to days in Python (no hallucinated names),
# and every day has a deterministic fallback so the itinerary is ALWAYS complete.

SUMMARY_DEADLINE_S = 40
MAX_PARALLEL_LLM = 6
MAX_LLM_DAYS = 10          # days beyond this use the deterministic template (keeps runtime bounded)


def _trip_dates(state: TripState) -> list[str]:
    try:
        start = datetime.strptime(state.get("start_date", ""), "%Y-%m-%d")
        end = datetime.strptime(state.get("end_date", ""), "%Y-%m-%d")
        n = max(1, (end - start).days + 1)
    except Exception:
        start, n = datetime.now(), 3
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(min(n, 21))]


def _pick(items: list, i: int, count: int) -> list:
    """Round-robin pick `count` distinct-as-possible items for day i."""
    if not items:
        return []
    out, n = [], len(items)
    for k in range(min(count, n)):
        out.append(items[(i * count + k) % n])
    return out


def _weather_for(state: TripState, i: int, date: str) -> str:
    daily = ((state.get("weather") or {}).get("daily")) or []
    row = next((d for d in daily if d.get("date") == date), None) or (daily[i] if i < len(daily) else None)
    if not row:
        return "weather not available"
    return (f"{row.get('condition', '?')}, {row.get('temp_min', 0):.0f}-{row.get('temp_max', 0):.0f}°C, "
            f"rain {row.get('precipitation_mm', 0):.1f}mm")


def _build_day_plan(state: TripState, i: int, date: str, n_days: int) -> dict:
    attractions = [a.get("name") for a in (state.get("attractions") or []) if a.get("name")]
    restaurants = [r.get("name") for r in (state.get("restaurants") or []) if r.get("name")]
    hotels = [h.get("name") for h in (state.get("hotels") or []) if h.get("name") and h.get("source") != "estimated_tier"]
    return {
        "day": i + 1,
        "date": date,
        "weather": _weather_for(state, i, date),
        "attractions": _pick(attractions, i, 3),
        "restaurants": _pick(restaurants, i, 2),
        "hotel": hotels[0] if hotels else None,
        "is_first": i == 0,
        "is_last": i == n_days - 1,
    }


def _fallback_day(plan: dict, dest: str, transport_tip: str) -> dict:
    a, r = plan["attractions"], plan["restaurants"]
    a1 = a[0] if a else None
    a2 = a[1] if len(a) > 1 else None
    a3 = a[2] if len(a) > 2 else None
    r1 = r[0] if r else None
    r2 = r[1] if len(r) > 1 else r1

    if plan["is_first"]:
        morning = f"Arrive in {dest}, check in{' at ' + plan['hotel'] if plan['hotel'] else ''} and freshen up. " + \
                  (f"Then take an easy first walk around {a1} to get your bearings." if a1 else "Take an easy first walk around the neighbourhood to get your bearings.")
    else:
        morning = (f"Start early at {a1} to beat the crowds - allow 2-3 hours to explore and take photos." if a1
                   else f"Free morning to explore {dest} at your own pace - wander local streets, cafes and markets.")
    afternoon = (f"Have lunch at {r1}" if r1 else "Have a relaxed local lunch") + \
                (f", then continue to {a2} for the afternoon." if a2 else ", then spend the afternoon exploring nearby areas and shops.")
    evening = (f"Head to {a3} as the light softens, then " if a3 else "Enjoy a slow evening stroll, then ") + \
              (f"dinner at {r2}." if r2 else "dinner at a well-reviewed local restaurant.")
    if plan["is_last"]:
        evening += " Pack up and prepare for departure."
    notes = f"Weather: {plan['weather']}."
    if "rain" in plan["weather"].lower() and not plan["weather"].endswith("rain 0.0mm"):
        notes += " Carry an umbrella or light rain jacket."
    if transport_tip:
        notes += f" Tip: {transport_tip}"
    return {"day": plan["day"], "date": plan["date"], "morning": morning,
            "afternoon": afternoon, "evening": evening, "notes": notes}


def _day_prompt(plan: dict, state: TripState, n_days: int) -> str:
    prefs = ", ".join(state.get("preferences", []) or []) or "general sightseeing"
    attrs = ", ".join(plan["attractions"]) or "none available"
    rests = ", ".join(plan["restaurants"]) or "none available"
    role = "first day (arrival)" if plan["is_first"] else ("last day (departure)" if plan["is_last"] else "regular sightseeing day")
    return f"""You are a travel itinerary writer. Write Day {plan['day']} of {n_days} for a {state.get('trip_type', 'leisure')} trip to {state.get('destination')} for {state.get('travelers', 1)} traveler(s).
Day type: {role}. Date: {plan['date']}. Weather: {plan['weather']}. Interests: {prefs}.
Hotel: {plan['hotel'] or 'not specified'}.
Places you MUST use for this day (use ONLY these names, do not invent other named places):
- Attractions: {attrs}
- Restaurants: {rests}

Write concrete, useful content: what to do, roughly how long, and a practical tip. 2 sentences each for morning, afternoon and evening. Add a short weather/packing/transport note.

Respond ONLY with valid JSON, no markdown, exactly this shape:
{{"morning": "...", "afternoon": "...", "evening": "...", "notes": "..."}}"""


def _valid_day(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    for f in ("morning", "afternoon", "evening"):
        v = obj.get(f)
        if isinstance(v, list):
            obj[f] = v = " ".join(str(x) for x in v)
        if not isinstance(v, str) or len(v.strip()) < 15 or _is_placeholder(v):
            return False
    if not isinstance(obj.get("notes"), str):
        obj["notes"] = str(obj.get("notes") or "")
    return True


async def _llm_day(llm, plan: dict, state: TripState, n_days: int, sem: asyncio.Semaphore, done_cb) -> Optional[dict]:
    async with sem:
        try:
            raw = await asyncio.to_thread(llm, _day_prompt(plan, state, n_days))
            obj = clean_json_response(raw)
            if isinstance(obj, list) and obj:
                obj = obj[0]
            if _valid_day(obj):
                return obj
        except Exception:
            return None
        finally:
            done_cb()
    return None


async def _llm_overview(llm, state: TripState, n_days: int) -> Optional[tuple]:
    attrs = ", ".join([a.get("name", "") for a in (state.get("attractions") or [])[:5]]) or "local highlights"
    prompt = (f"Write a catchy trip title (max 8 words) and a 2-3 sentence overview for a {n_days}-day "
              f"{state.get('trip_type', 'leisure')} trip to {state.get('destination')} for {state.get('travelers', 1)} traveler(s). "
              f"Highlights: {attrs}. Respond ONLY with JSON: "
              '{"trip_title": "...", "overview_paragraph": "..."}')
    try:
        obj = clean_json_response(await asyncio.to_thread(llm, prompt))
        if isinstance(obj, dict) and obj.get("trip_title") and obj.get("overview_paragraph"):
            return str(obj["trip_title"]), str(obj["overview_paragraph"])
    except Exception:
        pass
    return None


async def build_summary(state: TripState) -> TripState:
    """
    Build the full day-by-day itinerary. Days are generated in parallel (one small LLM call each)
    with a hard deadline; any day the LLM fails to produce gets a deterministic, data-driven
    fallback, so the result always covers EVERY day with morning/afternoon/evening/notes.
    """
    _init_errors(state)
    progress.set_status("summary", "running", "starting...")

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions") or []
        dest = suggs[0].get("destination") if suggs else "your destination"
        if suggs:
            state["destination"] = dest

    if not state.get("attractions"):
        state["errors"].append({"agent": "summary_agent", "message": "summary_agent: no attraction data available, itinerary built without attraction recommendations"})
    if not state.get("restaurants"):
        state["errors"].append({"agent": "summary_agent", "message": "summary_agent: no restaurant data available, itinerary built without restaurant recommendations"})

    dates = _trip_dates(state)
    n_days = len(dates)
    plans = [_build_day_plan(state, i, d, n_days) for i, d in enumerate(dates)]
    tips = ((state.get("transport_guide") or {}).get("tips")) or []
    transport_tip = tips[0] if tips and "unavailable" not in str(tips[0]).lower() else ""

    # Always have a complete deterministic itinerary ready first
    itinerary = [_fallback_day(p, dest or "your destination", transport_tip) for p in plans]
    overview = (f"Trip to {dest}", f"A {n_days}-day {state.get('trip_type', 'leisure')} itinerary for {dest}, "
                f"built from live weather, local attractions and restaurants, hotels and your budget.")

    llm_days = 0
    try:
        llm = get_llm(model=SMART_MODEL, max_tokens=700)
        sem = asyncio.Semaphore(MAX_PARALLEL_LLM)
        counter = {"n": 0}

        def tick():
            counter["n"] += 1
            progress.set_status("summary", "running", f"writing days... {counter['n']}/{min(n_days, MAX_LLM_DAYS)}")

        day_tasks = [asyncio.create_task(_llm_day(llm, plans[i], state, n_days, sem, tick))
                     for i in range(min(n_days, MAX_LLM_DAYS))]
        ov_task = asyncio.create_task(_llm_overview(llm, state, n_days))

        done, pending = await asyncio.wait(day_tasks + [ov_task], timeout=SUMMARY_DEADLINE_S)
        for t in pending:
            t.cancel()

        for i, t in enumerate(day_tasks):
            if t in done and not t.cancelled():
                res = t.result()
                if res:
                    itinerary[i].update({k: res[k] for k in ("morning", "afternoon", "evening", "notes") if res.get(k)})
                    llm_days += 1
        if ov_task in done and not ov_task.cancelled() and ov_task.result():
            overview = ov_task.result()
    except Exception as err:
        state["errors"].append({"agent": "summary_agent", "message": f"summary_agent: {err}"})

    if llm_days < min(n_days, MAX_LLM_DAYS):
        state["errors"].append({"agent": "summary_agent",
                                "message": f"summary_agent: AI wrote {llm_days}/{min(n_days, MAX_LLM_DAYS)} days; remaining days were generated from the retrieved places and weather."})

    itinerary[0]["_trip_title"] = overview[0]
    itinerary[0]["_overview"] = overview[1]
    state["daily_itinerary"] = itinerary

    progress.set_status("summary", "done" if llm_days == min(n_days, MAX_LLM_DAYS) else "warn",
                        f"{n_days} days ready")
    return state

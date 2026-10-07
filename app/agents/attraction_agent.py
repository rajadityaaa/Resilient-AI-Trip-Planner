"""
Attraction Agent: Fetches points of interest via Overpass and ranks them using LLM against user preferences.
"""
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.attraction_ranking_prompt import build_attraction_ranking_prompt
from app.tools.geocode_tools import geocode_place
from app.tools.places_tools import get_attractions


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


def _nominatim_places(kind: str, geo: dict) -> list:
    """Second real-data source (no LLM needed): Nominatim search inside a box around the city centre."""
    from app.tools.geocode_tools import search_places_nearby
    if kind == "attractions":
        queries, delta = ["tourist attraction", "museum", "temple", "park"], 0.05
    else:
        queries, delta = ["restaurant", "cafe"], 0.025
    out, seen = [], set()
    for q in queries:
        for it in search_places_nearby(q, geo["lat"], geo["lon"], delta=delta, limit=15):
            key = it["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": it["name"], "category": (it.get("type") or q).replace("_", " ").capitalize(),
                        "lat": it["lat"], "lon": it["lon"], "tags": {}})
    return out[:20]


def _ai_place_fallback(kind: str, dest: str, prefs: list, geo: dict) -> list:
    """OSM returned nothing -> ask the LLM for well-known real places. Flagged as AI-suggested."""
    from app.llm.prompts.place_fallback_prompt import build_place_fallback_prompt
    from app.llm.factory import SMART_MODEL
    llm = get_llm(model=SMART_MODEL, max_tokens=1800)
    prompt = build_place_fallback_prompt(kind, dest, prefs, geo["lat"], geo["lon"])
    items = clean_json_response(llm(prompt))
    if isinstance(items, dict):
        items = [items]
    out, seen = [], set()
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            lat, lon = float(it.get("lat")), float(it.get("lon"))
            if abs(lat - geo["lat"]) > 0.5 or abs(lon - geo["lon"]) > 0.5:
                raise ValueError
        except Exception:
            lat, lon = geo["lat"], geo["lon"]      # keep pin near the city centre if AI coords are off
        out.append({"name": name, "category": it.get("category", kind.capitalize()), "lat": lat, "lon": lon,
                    "match_reason": it.get("match_reason", ""), "source": "ai_suggested"})
    return out[:10]


async def get_attractions_for_trip(state: TripState) -> TripState:
    """
    Fetch attractions near destination and rank them using LLM.
    Capped at top 10 items.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "attraction_agent", "message": "No destination available."})
        state["attractions"] = []
        return state

    try:
        geo = geocode_place(dest)
        raw_attractions = get_attractions(geo["lat"], geo["lon"], radius_m=5000, limit=20)

        if not raw_attractions:
            # OSM empty: famous-landmark suggestions from the AI are the best tourist list; real-data search is the backup.
            try:
                ai_list = _ai_place_fallback("attractions", dest, state.get("preferences", []), geo)
            except Exception:
                ai_list = []
            if ai_list:
                state["attractions"] = ai_list
                state["errors"].append({"agent": "attraction_agent", "message": "attraction_agent: OpenStreetMap had no data; AI-suggested landmarks used"})
                return state
            raw_attractions = _nominatim_places("attractions", geo)
            if not raw_attractions:
                state["attractions"] = []
                return state

        # Use LLM to rank and filter raw attractions according to user preferences
        try:
            llm = get_llm()
            prompt = build_attraction_ranking_prompt(state.get("preferences", []), raw_attractions)
            resp_text = llm(prompt)
            
            try:
                ranked = clean_json_response(resp_text)
            except json.JSONDecodeError:
                # Retry once with stricter formatting instructions
                retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
                resp_text = llm(prompt + retry_instruction)
                try:
                    ranked = clean_json_response(resp_text)
                except json.JSONDecodeError:
                    # Log a non-technical error and fall back to raw list slice
                    state["errors"].append({
                        "agent": "attraction_agent",
                        "message": "attraction_agent: LLM response could not be parsed after retry, using raw attractions"
                    })
                    state["attractions"] = raw_attractions[:10]
                    return state

            if isinstance(ranked, list) and len(ranked) > 0:
                # Deduplicate by name (LLM may repeat entries)
                seen = set()
                deduped = []
                for a in ranked:
                    aname = (a.get("name") or "").strip().lower()
                    if aname and aname not in seen:
                        seen.add(aname)
                        deduped.append(a)
                state["attractions"] = deduped[:10]
            else:
                state["attractions"] = raw_attractions[:10]
        except Exception:
            # Fall back to raw list slice if LLM fails
            state["attractions"] = raw_attractions[:10]

    except Exception as err:
        state["errors"].append({"agent": "attraction_agent", "message": str(err)})
        state["attractions"] = []

    return state


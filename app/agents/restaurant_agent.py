"""
Restaurant Agent: Fetches dining options via Overpass and flags best matches using LLM.
"""
import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.restaurant_ranking_prompt import build_restaurant_ranking_prompt
from app.tools.geocode_tools import geocode_place
from app.tools.places_tools import get_restaurants


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


async def get_restaurants_for_trip(state: TripState) -> TripState:
    """
    Fetch restaurants near destination, pass detected cuisine filter, and rank using LLM.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    if not dest:
        state["errors"].append({"agent": "restaurant_agent", "message": "No destination available."})
        state["restaurants"] = []
        return state

    try:
        geo = geocode_place(dest)

        # Detect cuisine keywords from user preferences
        prefs = state.get("preferences", [])
        cuisine_kw = None
        for p in prefs:
            p_lower = p.lower()
            if any(k in p_lower for k in ["italian", "indian", "chinese", "japanese", "mexican", "thai", "vegetarian", "vegan", "seafood", "street food"]):
                cuisine_kw = p
                break

        raw_restaurants = get_restaurants(geo["lat"], geo["lon"], radius_m=3000, cuisine=cuisine_kw, limit=20)
        if not raw_restaurants and cuisine_kw:
            # Fall back without cuisine filter if strict filter returned 0
            raw_restaurants = get_restaurants(geo["lat"], geo["lon"], radius_m=3000, cuisine=None, limit=20)

        if not raw_restaurants:
            raw_restaurants = _nominatim_places("restaurants", geo)

        if not raw_restaurants:
            try:
                state["restaurants"] = _ai_place_fallback("restaurants", dest, prefs, geo)
                state["errors"].append({"agent": "restaurant_agent", "message": "restaurant_agent: OpenStreetMap had no data; AI-suggested dining spots used"})
            except Exception:
                state["restaurants"] = []
            return state

        # Use LLM to rank and match restaurants
        try:
            llm = get_llm()
            prompt = build_restaurant_ranking_prompt(prefs, raw_restaurants)
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
                        "agent": "restaurant_agent",
                        "message": "restaurant_agent: LLM response could not be parsed after retry, using raw restaurants"
                    })
                    state["restaurants"] = raw_restaurants[:10]
                    return state

            if isinstance(ranked, list) and len(ranked) > 0:
                # Deduplicate by name (LLM may repeat entries)
                seen = set()
                deduped = []
                for r in ranked:
                    rname = (r.get("name") or "").strip().lower()
                    if rname and rname not in seen:
                        seen.add(rname)
                        deduped.append(r)
                state["restaurants"] = deduped[:10]
            else:
                state["restaurants"] = raw_restaurants[:10]
        except Exception:
            state["restaurants"] = raw_restaurants[:10]

    except Exception as err:
        state["errors"].append({"agent": "restaurant_agent", "message": str(err)})
        state["restaurants"] = []

    return state

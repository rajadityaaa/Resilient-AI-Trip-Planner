"""
Attraction Agent: Fetches points of interest via Provider Registry (Foursquare -> Overpass -> Nominatim -> AI)
and ranks them using LLM against user preferences.
"""
from __future__ import annotations

import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.attraction_ranking_prompt import build_attraction_ranking_prompt
from app.providers.registry import search_places
from app.tools.geocode_tools import geocode_place


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


def _ai_place_fallback(kind: str, dest: str, prefs: list, geo: dict) -> list:
    """Providers returned nothing -> ask the LLM for well-known real places. Flagged as AI-suggested."""
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
            lat, lon = geo["lat"], geo["lon"]
        out.append({
            "name": name,
            "category": it.get("category", kind.capitalize()),
            "lat": lat,
            "lon": lon,
            "match_reason": it.get("match_reason", ""),
            "source": "ai_suggested",
            "tags": {},
        })
    return out[:10]


async def get_attractions_for_trip(state: TripState) -> TripState:
    """
    Fetch attractions near destination via provider chain and rank them using LLM.
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
        raw_attractions, source = search_places(
            kind="attractions",
            lat=geo["lat"],
            lon=geo["lon"],
            radius_m=5000,
            limit=20,
            destination=dest,
        )

        if not raw_attractions:
            # Fall back to AI landmark suggestions if all providers returned nothing
            try:
                ai_list = _ai_place_fallback("attractions", dest, state.get("preferences", []), geo)
            except Exception:
                ai_list = []
            if ai_list:
                state["attractions"] = ai_list
                state["errors"].append({
                    "agent": "attraction_agent",
                    "message": "attraction_agent: Real data providers had no data; AI-suggested landmarks used",
                })
                return state
            state["attractions"] = []
            return state

        # Index raw attractions by name to preserve provider metadata during LLM ranking
        raw_by_name = {
            a["name"].strip().lower(): a for a in raw_attractions if isinstance(a, dict) and a.get("name")
        }

        # Use LLM to rank and filter raw attractions according to user preferences
        try:
            llm = get_llm()
            prompt = build_attraction_ranking_prompt(state.get("preferences", []), raw_attractions)
            resp_text = llm(prompt)

            try:
                ranked = clean_json_response(resp_text)
            except json.JSONDecodeError:
                retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON, no trailing commas, no comments, and properly escaped quotes."
                resp_text = llm(prompt + retry_instruction)
                try:
                    ranked = clean_json_response(resp_text)
                except json.JSONDecodeError:
                    state["errors"].append({
                        "agent": "attraction_agent",
                        "message": "attraction_agent: LLM response could not be parsed after retry, using raw attractions",
                    })
                    state["attractions"] = raw_attractions[:10]
                    return state

            if isinstance(ranked, list) and len(ranked) > 0:
                seen = set()
                deduped = []
                for a in ranked:
                    aname = (a.get("name") or "").strip().lower()
                    if aname and aname not in seen:
                        seen.add(aname)
                        # Merge metadata from original provider result
                        original = raw_by_name.get(aname, {})
                        merged = {
                            "name": a.get("name") or original.get("name", "Attraction"),
                            "category": a.get("category") or original.get("category", "Attraction"),
                            "lat": original.get("lat") or a.get("lat", geo["lat"]),
                            "lon": original.get("lon") or a.get("lon", geo["lon"]),
                            "tags": original.get("tags", {}),
                            "match_reason": a.get("match_reason", ""),
                            "rating": original.get("rating"),
                            "price_level": original.get("price_level"),
                            "website": original.get("website"),
                            "source": original.get("source", source),
                        }
                        deduped.append(merged)
                state["attractions"] = deduped[:10]
            else:
                state["attractions"] = raw_attractions[:10]
        except Exception:
            state["attractions"] = raw_attractions[:10]

    except Exception as err:
        state["errors"].append({"agent": "attraction_agent", "message": str(err)})
        state["attractions"] = []

    return state

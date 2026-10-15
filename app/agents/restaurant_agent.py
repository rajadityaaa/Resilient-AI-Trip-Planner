"""
Restaurant Agent: Fetches dining options via Provider Registry (Foursquare -> Overpass -> Nominatim -> AI)
and ranks best matches using LLM.
"""
from __future__ import annotations

import json
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response
from app.llm.prompts.restaurant_ranking_prompt import build_restaurant_ranking_prompt
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

        raw_restaurants, source = search_places(
            kind="restaurants",
            lat=geo["lat"],
            lon=geo["lon"],
            radius_m=3000,
            limit=20,
            query=cuisine_kw,
            destination=dest,
        )

        if not raw_restaurants and cuisine_kw:
            # Fall back without cuisine filter if strict filter returned 0
            raw_restaurants, source = search_places(
                kind="restaurants",
                lat=geo["lat"],
                lon=geo["lon"],
                radius_m=3000,
                limit=20,
                query=None,
                destination=dest,
            )

        if not raw_restaurants:
            try:
                state["restaurants"] = _ai_place_fallback("restaurants", dest, prefs, geo)
                state["errors"].append({
                    "agent": "restaurant_agent",
                    "message": "restaurant_agent: Real data providers had no data; AI-suggested dining spots used",
                })
            except Exception:
                state["restaurants"] = []
            return state

        # Soft sort raw restaurants by user preferences/cuisine before LLM ranking
        if prefs or cuisine_kw:
            match_terms = [p.lower() for p in prefs]
            if cuisine_kw and cuisine_kw.lower() not in match_terms:
                match_terms.append(cuisine_kw.lower())

            def _score_restaurant(r: dict) -> int:
                score = 0
                name = (r.get("name") or "").lower()
                cat = (r.get("category") or "").lower()
                tags = r.get("tags") or {}
                cuisine_tag = str(tags.get("cuisine", "")).lower()
                for term in match_terms:
                    if term in name:
                        score += 3
                    if term in cuisine_tag:
                        score += 3
                    if term in cat:
                        score += 2
                return score

            raw_restaurants.sort(key=_score_restaurant, reverse=True)

        # Index raw items by name to preserve provider metadata
        raw_by_name = {
            r["name"].strip().lower(): r for r in raw_restaurants if isinstance(r, dict) and r.get("name")
        }

        # Use LLM to rank and match restaurants
        try:
            llm = get_llm()
            prompt = build_restaurant_ranking_prompt(prefs, raw_restaurants)
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
                        "agent": "restaurant_agent",
                        "message": "restaurant_agent: LLM response could not be parsed after retry, using raw restaurants",
                    })
                    state["restaurants"] = raw_restaurants[:10]
                    return state

            if isinstance(ranked, list) and len(ranked) > 0:
                seen = set()
                deduped = []
                for r in ranked:
                    rname = (r.get("name") or "").strip().lower()
                    if rname and rname not in seen:
                        seen.add(rname)
                        original = raw_by_name.get(rname, {})
                        merged = {
                            "name": r.get("name") or original.get("name", "Restaurant"),
                            "category": r.get("category") or original.get("category", "Restaurant"),
                            "lat": original.get("lat") or r.get("lat", geo["lat"]),
                            "lon": original.get("lon") or r.get("lon", geo["lon"]),
                            "tags": original.get("tags", {}),
                            "match_reason": r.get("match_reason", ""),
                            "rating": original.get("rating"),
                            "price_level": original.get("price_level"),
                            "website": original.get("website"),
                            "source": original.get("source", source),
                        }
                        deduped.append(merged)

                # Backfill from raw_restaurants if LLM returned fewer than 10 items
                if len(deduped) < 10 and len(raw_restaurants) > len(deduped):
                    for r in raw_restaurants:
                        rname = (r.get("name") or "").strip().lower()
                        if rname and rname not in seen:
                            seen.add(rname)
                            deduped.append(r)
                            if len(deduped) >= 10:
                                break

                state["restaurants"] = deduped[:10]
            else:
                state["restaurants"] = raw_restaurants[:10]
        except Exception:
            state["restaurants"] = raw_restaurants[:10]

    except Exception as err:
        state["errors"].append({"agent": "restaurant_agent", "message": str(err)})
        state["restaurants"] = []

    return state

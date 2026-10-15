"""
Attraction Agent: Fetches points of interest via Provider Registry (Foursquare -> Overpass -> Nominatim -> AI)
and ranks them using LLM against user preferences.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from app.agents.state import TripState
from app.llm.factory import get_llm, clean_json_response, FAST_MODEL
from app.providers.registry import search_places
from app.tools.geocode_tools import geocode_place

logger = logging.getLogger(__name__)


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate approximate distance between two GPS coordinates in meters."""
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)) * 111320.0
    y = (lat2 - lat1) * 110540.0
    return math.sqrt(x * x + y * y)


def _name_similarity(n1: str, n2: str) -> bool:
    """Return True if two landmark names are likely variations of the same place."""
    s1, s2 = n1.lower().strip(), n2.lower().strip()
    if s1 == s2:
        return True
    if len(s1) >= 4 and len(s2) >= 4:
        if s1 in s2 or s2 in s1:
            return True
    w1 = set(s1.replace("(", " ").replace(")", " ").replace("-", " ").split())
    w2 = set(s2.replace("(", " ").replace(")", " ").replace("-", " ").split())
    common = w1.intersection(w2)
    stop = {"the", "of", "and", "in", "at", "near", "a", "temple", "museum", "park"}
    sig_common = [w for w in common if w not in stop and len(w) >= 3]
    return len(sig_common) > 0


def _ai_place_fallback(kind: str, dest: str, prefs: list, geo: dict, count: int = 8) -> list:
    """Ask the LLM for 8 famous, real attractions in destination matching user preferences."""
    from app.llm.prompts.place_fallback_prompt import build_place_fallback_prompt
    llm = get_llm(model=FAST_MODEL, max_tokens=1800)
    prompt = build_place_fallback_prompt(kind, dest, prefs, geo["lat"], geo["lon"])
    try:
        items = clean_json_response(llm(prompt))
    except Exception:
        retry_instruction = "\n\nCRITICAL: Respond with ONLY valid JSON array with no extra text."
        items = clean_json_response(llm(prompt + retry_instruction))
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
            "category": it.get("category", "Attraction"),
            "lat": lat,
            "lon": lon,
            "match_reason": it.get("match_reason", ""),
            "source": "ai_suggested",
            "tags": {},
        })
    return out[:count]


async def get_attractions_for_trip(state: TripState) -> TripState:
    """
    Fetch attractions near destination combining:
    1. Up to 6 AI-suggested famous landmarks matching user preferences.
    2. Up to 6 best real places from the provider chain (Overpass -> Nominatim).
    Deduplicated by case-insensitive name & distance < 150m, capped at 12 in total.
    Runs AI and provider lookups concurrently in parallel.
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
        prefs = state.get("preferences", []) or []

        def _fetch_ai_landmarks() -> list[dict]:
            try:
                return _ai_place_fallback("attractions", dest, prefs, geo, count=8)
            except Exception as exc:
                logger.warning(f"[AttractionAgent] AI landmark lookup failed: {exc}")
                return []

        def _fetch_provider_attractions() -> list[dict]:
            try:
                raw, _ = search_places(
                    kind="attractions",
                    lat=geo["lat"],
                    lon=geo["lon"],
                    radius_m=5000,
                    limit=20,
                    destination=dest,
                    preferences=prefs,
                )
                return raw
            except Exception as exc:
                logger.warning(f"[AttractionAgent] Provider lookup failed: {exc}")
                return []

        # Run LLM landmark call and provider chain lookup concurrently
        ai_places, real_places = await asyncio.gather(
            asyncio.to_thread(_fetch_ai_landmarks),
            asyncio.to_thread(_fetch_provider_attractions),
        )

        # Rank real places matching preferences higher than ones that don't
        if prefs and real_places:
            pref_terms = [p.lower() for p in prefs]
            expanded = set(pref_terms)
            for t in pref_terms:
                if t.endswith("s") and len(t) > 3:
                    expanded.add(t[:-1])

            def _score_real(r: dict) -> int:
                score = 0
                name = (r.get("name") or "").lower()
                cat = (r.get("category") or "").lower()
                tags = r.get("tags") or {}
                for term in expanded:
                    if term in name:
                        score += 3
                    if term in cat:
                        score += 2
                    if any(term in str(v).lower() for v in tags.values()):
                        score += 2
                return score

            real_places.sort(key=_score_real, reverse=True)

        # Merge: AI-suggested first (up to 6), then best real places (up to 6)
        # Deduplicated by case-insensitive name & distance < 150m for similar names
        merged = []
        seen_names = set()

        def _is_duplicate(item: dict) -> bool:
            iname = (item.get("name") or "").strip().lower()
            if not iname or iname in seen_names:
                return True
            ilat, ilon = item.get("lat"), item.get("lon")
            for ex in merged:
                ename = (ex.get("name") or "").strip().lower()
                if iname == ename:
                    return True
                elat, elon = ex.get("lat"), ex.get("lon")
                if ilat is not None and ilon is not None and elat is not None and elon is not None:
                    try:
                        dist = _haversine_m(float(ilat), float(ilon), float(elat), float(elon))
                        if dist < 150 and _name_similarity(iname, ename):
                            return True
                    except Exception:
                        pass
            return False

        # Add up to 6 AI-suggested landmarks
        ai_added = 0
        for a in ai_places:
            if not _is_duplicate(a):
                seen_names.add(a["name"].strip().lower())
                merged.append(a)
                ai_added += 1
                if ai_added >= 6:
                    break

        # Add up to 6 real places
        real_added = 0
        for r in real_places:
            if not _is_duplicate(r):
                seen_names.add(r["name"].strip().lower())
                merged.append(r)
                real_added += 1
                if real_added >= 6 or len(merged) >= 12:
                    break

        # Fallback if both returned nothing
        if not merged:
            if real_places:
                merged = real_places[:10]
            elif ai_places:
                merged = ai_places[:10]

        state["attractions"] = merged[:12]

    except Exception as err:
        state["errors"].append({"agent": "attraction_agent", "message": str(err)})
        state["attractions"] = []

    return state

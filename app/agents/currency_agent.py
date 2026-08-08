"""
Currency Agent: Retrieves exchange rate data and localized tipping/cash advice.

Uses geocode_place to resolve the destination's country, then maps that country
to an ISO currency code via COUNTRY_CURRENCY_MAP before calling convert_currency.
"""
from app.agents.state import TripState
from app.llm.factory import get_llm
from app.llm.prompts.currency_prompt import build_currency_prompt
from app.tools.currency_tools import convert_currency
from app.tools.geocode_tools import geocode_place

# Map country names (lowercase) returned by Nominatim to ISO 4217 currency codes.
# Nominatim returns full country names (e.g. "India", "France", "Thailand"),
# so we normalize to lowercase for matching.
COUNTRY_CURRENCY_MAP = {
    "india": "INR",
    "france": "EUR",
    "germany": "EUR",
    "italy": "EUR",
    "spain": "EUR",
    "portugal": "EUR",
    "netherlands": "EUR",
    "belgium": "EUR",
    "austria": "EUR",
    "greece": "EUR",
    "ireland": "EUR",
    "finland": "EUR",
    "united kingdom": "GBP",
    "uk": "GBP",
    "japan": "JPY",
    "united states": "USD",
    "united states of america": "USD",
    "usa": "USD",
    "us": "USD",
    "canada": "CAD",
    "australia": "AUD",
    "new zealand": "NZD",
    "thailand": "THB",
    "singapore": "SGD",
    "malaysia": "MYR",
    "indonesia": "IDR",
    "vietnam": "VND",
    "philippines": "PHP",
    "south korea": "KRW",
    "china": "CNY",
    "taiwan": "TWD",
    "switzerland": "CHF",
    "mexico": "MXN",
    "brazil": "BRL",
    "argentina": "ARS",
    "colombia": "COP",
    "turkey": "TRY",
    "south africa": "ZAR",
    "egypt": "EGP",
    "morocco": "MAD",
    "united arab emirates": "AED",
    "saudi arabia": "SAR",
    "qatar": "QAR",
    "russia": "RUB",
    "sweden": "SEK",
    "norway": "NOK",
    "denmark": "DKK",
    "czech republic": "CZK",
    "czechia": "CZK",
    "poland": "PLN",
    "hungary": "HUF",
    "croatia": "EUR",
    "romania": "RON",
    "sri lanka": "LKR",
    "nepal": "NPR",
    "bangladesh": "BDT",
    "pakistan": "PKR",
    "kenya": "KES",
    "nigeria": "NGN",
    "peru": "PEN",
    "chile": "CLP",
}


def _detect_local_currency(dest: str) -> tuple[str, str]:
    """
    Detect local currency code and country name from destination string.

    Strategy:
    1. Geocode the destination to get the country name from Nominatim.
    2. Look up that country in COUNTRY_CURRENCY_MAP.
    3. If geocoding fails, fall back to substring matching against the
       destination string itself (handles cases like "Paris, France").
    4. Final fallback: return user's budget currency (USD).
    """
    if not dest:
        return "USD", "Unknown"

    # Step 1: Try geocoding to resolve the actual country
    try:
        geo = geocode_place(dest)
        country = geo.get("country", "")
        if country:
            country_lower = country.lower()
            if country_lower in COUNTRY_CURRENCY_MAP:
                return COUNTRY_CURRENCY_MAP[country_lower], country
    except Exception:
        pass  # geocoding failed, fall through to substring matching

    # Step 2: Substring matching fallback (handles "Jaipur, India" etc.)
    dest_lower = dest.lower()
    for country_key, curr_code in COUNTRY_CURRENCY_MAP.items():
        if country_key in dest_lower:
            return curr_code, country_key.title()

    # Step 3: Final fallback
    return "USD", dest


def _init_errors(state: TripState):
    if "errors" not in state or state["errors"] is None:
        state["errors"] = []


async def build_currency_info(state: TripState) -> TripState:
    """
    Determine local currency, convert total budget, and generate cash & tipping guidance.
    """
    _init_errors(state)

    dest = state.get("destination")
    if not dest:
        suggs = state.get("destination_suggestions", [])
        if suggs and len(suggs) > 0:
            dest = suggs[0].get("destination")

    local_curr, country_name = _detect_local_currency(dest or "")
    user_budget = float(state.get("budget_total", 1000.0))
    user_curr = state.get("budget_currency", "USD")

    try:
        conversion = convert_currency(user_budget, user_curr, local_curr)

        cash_tips = "Credit cards are widely accepted. Carry small amounts of local cash for street markets."
        try:
            llm = get_llm()
            prompt = build_currency_prompt(country_name, local_curr)
            cash_tips = llm(prompt).strip()
        except Exception:
            pass

        state["currency_info"] = {
            "local_currency": local_curr,
            "converted_budget": conversion["converted_amount"],
            "exchange_rate": conversion["rate"],
            "cash_tips": cash_tips
        }
    except Exception as err:
        state["errors"].append({"agent": "currency_agent", "message": str(err)})
        state["currency_info"] = {
            "local_currency": local_curr,
            "converted_budget": user_budget,
            "exchange_rate": 1.0,
            "cash_tips": "Credit cards accepted in major establishments."
        }

    return state

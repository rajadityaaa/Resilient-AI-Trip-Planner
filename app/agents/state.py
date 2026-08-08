from typing import TypedDict, Optional, Literal


class TripState(TypedDict):
    # user inputs
    origin: str
    destination: Optional[str]          # None if user wants suggestions instead
    start_date: str                     # ISO date
    end_date: str
    travelers: int
    budget_total: float
    budget_currency: str                # ISO code, e.g. "USD"
    trip_type: Literal["leisure", "business", "adventure", "family", "solo", "romantic"]
    preferences: list[str]              # e.g. ["museums", "street food", "hiking"]

    # agent outputs, populated as the graph runs
    destination_suggestions: Optional[list[dict]]
    weather: Optional[dict]
    attractions: Optional[list[dict]]
    restaurants: Optional[list[dict]]
    hotels: Optional[list[dict]]
    budget_breakdown: Optional[dict]
    transport_guide: Optional[dict]
    packing_list: Optional[list[str]]
    currency_info: Optional[dict]
    daily_itinerary: Optional[list[dict]]  # final Summary Agent output
    errors: list[dict]                     # {agent: str, message: str} — never crash, always log

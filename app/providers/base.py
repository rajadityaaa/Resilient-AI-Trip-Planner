"""
Base definitions and Protocol for Places providers.
"""
from __future__ import annotations

from typing import Literal, Optional, Protocol, runtime_checkable

KindType = Literal["attractions", "restaurants", "hotels"]


@runtime_checkable
class PlacesProvider(Protocol):
    """Protocol implemented by all external place data providers."""

    name: str

    def search(
        self,
        kind: KindType,
        lat: float,
        lon: float,
        radius_m: int,
        limit: int,
        query: Optional[str] = None,
    ) -> list[dict]:
        """
        Search for places of a given kind near (lat, lon).

        Args:
            kind: "attractions", "restaurants", or "hotels"
            lat: Latitude of search center
            lon: Longitude of search center
            radius_m: Search radius in meters
            limit: Maximum items to return
            query: Optional free-text search or cuisine/tag filter

        Returns:
            List of normalized place dictionaries.
        """
        ...

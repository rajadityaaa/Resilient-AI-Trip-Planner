"""
Unit tests for all 9 reasoning agents in app.agents.
Tests each agent standalone using asyncio.
"""
import unittest
import asyncio
from app.agents.state import TripState
from app.agents.destination_agent import suggest_destinations
from app.agents.weather_agent import get_weather
from app.agents.attraction_agent import get_attractions_for_trip
from app.agents.restaurant_agent import get_restaurants_for_trip
from app.agents.hotel_agent import get_hotels
from app.agents.budget_agent import build_budget
from app.agents.transport_agent import build_transport_guide
from app.agents.packing_agent import build_packing_list
from app.agents.currency_agent import build_currency_info


class TestAllAgents(unittest.TestCase):

    def setUp(self):
        self.sample_state: TripState = {
            "origin": "New Delhi",
            "destination": "Jaipur, India",
            "start_date": "2026-09-01",
            "end_date": "2026-09-05",
            "travelers": 2,
            "budget_total": 1500.0,
            "budget_currency": "USD",
            "trip_type": "leisure",
            "preferences": ["heritage", "museums", "street food"],
            "destination_suggestions": None,
            "weather": None,
            "attractions": None,
            "restaurants": None,
            "hotels": None,
            "budget_breakdown": None,
            "transport_guide": None,
            "packing_list": None,
            "currency_info": None,
            "daily_itinerary": None,
            "errors": []
        }

    def test_destination_agent_supplied(self):
        """Test destination agent skips when destination is already supplied."""
        res = asyncio.run(suggest_destinations(dict(self.sample_state)))
        self.assertEqual(res["destination"], "Jaipur, India")

    def test_destination_agent_suggestion(self):
        """Test destination agent generates suggestions when destination is None."""
        state_none_dest = dict(self.sample_state)
        state_none_dest["destination"] = None

        res = asyncio.run(suggest_destinations(state_none_dest))
        self.assertIsInstance(res.get("destination_suggestions"), list)

    def test_weather_agent(self):
        """Test weather agent populates weather dict."""
        res = asyncio.run(get_weather(dict(self.sample_state)))
        self.assertIn("weather", res)
        if res["weather"] is not None:
            self.assertIn("daily", res["weather"])

    def test_attraction_agent(self):
        """Test attraction agent populates attractions list."""
        res = asyncio.run(get_attractions_for_trip(dict(self.sample_state)))
        self.assertIn("attractions", res)
        self.assertIsInstance(res["attractions"], list)

    def test_restaurant_agent(self):
        """Test restaurant agent populates restaurants list."""
        res = asyncio.run(get_restaurants_for_trip(dict(self.sample_state)))
        self.assertIn("restaurants", res)
        self.assertIsInstance(res["restaurants"], list)

    def test_hotel_agent(self):
        """Test hotel agent populates hotels list."""
        res = asyncio.run(get_hotels(dict(self.sample_state)))
        self.assertIn("hotels", res)
        self.assertIsInstance(res["hotels"], list)
        self.assertGreaterEqual(len(res["hotels"]), 1)

    def test_budget_agent(self):
        """Test budget agent populates budget breakdown and validates sum."""
        res = asyncio.run(build_budget(dict(self.sample_state)))
        self.assertIn("budget_breakdown", res)
        breakdown = res["budget_breakdown"]
        self.assertIsInstance(breakdown, dict)

        total_sum = sum(breakdown.values())
        self.assertAlmostEqual(total_sum, 1500.0, delta=15.0)

    def test_transport_agent(self):
        """Test transport agent populates transport guide dict."""
        res = asyncio.run(build_transport_guide(dict(self.sample_state)))
        self.assertIn("transport_guide", res)
        self.assertIsInstance(res["transport_guide"], dict)

    def test_packing_agent(self):
        """Test packing agent populates packing checklist list."""
        res = asyncio.run(build_packing_list(dict(self.sample_state)))
        self.assertIn("packing_list", res)
        self.assertIsInstance(res["packing_list"], list)
        self.assertGreaterEqual(len(res["packing_list"]), 1)

    def test_currency_agent(self):
        """Test currency agent populates currency info dict."""
        res = asyncio.run(build_currency_info(dict(self.sample_state)))
        self.assertIn("currency_info", res)
        curr = res["currency_info"]
        self.assertEqual(curr["local_currency"], "INR")
        self.assertGreater(curr["converted_budget"], 0.0)

    def test_agent_error_isolation(self):
        """Test that agents capture errors gracefully without crashing."""
        invalid_state: TripState = {
            "origin": "",
            "destination": None,
            "start_date": "invalid_date",
            "end_date": "invalid_date",
            "travelers": -1,
            "budget_total": -500.0,
            "budget_currency": "INVALID",
            "trip_type": "leisure",
            "preferences": [],
            "destination_suggestions": None,
            "weather": None,
            "attractions": None,
            "restaurants": None,
            "hotels": None,
            "budget_breakdown": None,
            "transport_guide": None,
            "packing_list": None,
            "currency_info": None,
            "daily_itinerary": None,
            "errors": []
        }

        # Running weather_agent on invalid state should append error and not raise
        res = asyncio.run(get_weather(invalid_state))
        self.assertGreaterEqual(len(res["errors"]), 1)


if __name__ == "__main__":
    unittest.main()

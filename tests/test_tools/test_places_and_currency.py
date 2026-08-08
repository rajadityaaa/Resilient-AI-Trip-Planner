"""
Unit tests for app.tools.places_tools and app.tools.currency_tools.
"""
import time
import unittest
from app.tools.cache import cache_clear
from app.tools.places_tools import get_attractions, get_restaurants, _fetch_overpass_with_retry
from app.tools.currency_tools import convert_currency


class TestPlacesAndCurrency(unittest.TestCase):

    def test_get_attractions_jaipur(self):
        """Test fetching real attractions for Jaipur, India."""
        cache_clear()
        results = get_attractions(26.915, 75.818, radius_m=5000, limit=5)

        self.assertIsInstance(results, list)
        if len(results) > 0:
            first = results[0]
            self.assertIn("name", first)
            self.assertIn("category", first)
            self.assertIn("lat", first)
            self.assertIn("lon", first)
            self.assertIn("tags", first)

    def test_get_restaurants_and_cuisine(self):
        """Test fetching restaurants and client-side cuisine filtering."""
        cache_clear()
        results = get_restaurants(26.915, 75.818, radius_m=3000, limit=5)
        self.assertIsInstance(results, list)

        # Test with cuisine filter
        cache_clear()
        indian_results = get_restaurants(26.915, 75.818, radius_m=5000, cuisine="indian", limit=5)
        self.assertIsInstance(indian_results, list)

    def test_overpass_retry_backoff(self):
        """Test that _fetch_overpass_with_retry retries on endpoint failure and returns None cleanly."""
        start_time = time.time()
        res = _fetch_overpass_with_retry("invalid_query", attempts=2, url="https://httpbin.org/status/500")
        elapsed = time.time() - start_time

        self.assertIsNone(res)
        # 2 attempts with 2s sleep before 2nd attempt -> elapsed >= 2.0s
        self.assertGreaterEqual(elapsed, 1.8)

    def test_convert_currency_usd_inr(self):
        """Test Frankfurter currency conversion for USD -> INR."""
        cache_clear()
        res = convert_currency(100.0, "USD", "INR")

        self.assertIsInstance(res, dict)
        self.assertEqual(res["from_code"], "USD")
        self.assertEqual(res["to_code"], "INR")
        self.assertGreater(res["rate"], 0.0)
        self.assertGreater(res["converted_amount"], 0.0)
        self.assertEqual(res["amount"], 100.0)

    def test_convert_currency_same_code(self):
        """Test short-circuit behavior when converting same currency (USD -> USD)."""
        cache_clear()
        res = convert_currency(150.0, "USD", "USD")

        self.assertIsInstance(res, dict)
        self.assertEqual(res["from_code"], "USD")
        self.assertEqual(res["to_code"], "USD")
        self.assertEqual(res["rate"], 1.0)
        self.assertEqual(res["converted_amount"], 150.0)


if __name__ == "__main__":
    unittest.main()

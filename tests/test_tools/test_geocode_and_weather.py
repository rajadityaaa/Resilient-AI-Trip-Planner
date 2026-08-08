"""
Unit tests for app.tools.geocode_tools and app.tools.weather_tools.
Uses standard library unittest so it runs everywhere.
"""
import time
import unittest
from datetime import datetime, timedelta
from app.tools.cache import cache_clear
from app.tools.geocode_tools import geocode_place, GeocodeNotFoundError
from app.tools.weather_tools import get_forecast


class TestGeocodeAndWeather(unittest.TestCase):

    def test_geocode_place_success(self):
        """Test geocoding a real city (Jaipur, India)."""
        cache_clear()
        res = geocode_place("Jaipur, India")

        self.assertIsInstance(res, dict)
        self.assertIn("lat", res)
        self.assertIn("lon", res)
        self.assertIn("display_name", res)
        self.assertIn("country", res)
        self.assertIn("bounding_box", res)

        # Verify Jaipur coordinates (lat ~26.9, lon ~75.8)
        self.assertAlmostEqual(res["lat"], 26.91, delta=0.5)
        self.assertAlmostEqual(res["lon"], 75.81, delta=0.5)
        self.assertTrue("India" in res["country"] or "India" in res["display_name"])

    def test_geocode_place_not_found(self):
        """Test geocoding an invalid location query raises GeocodeNotFoundError."""
        cache_clear()
        with self.assertRaises(GeocodeNotFoundError):
            geocode_place("xyz_non_existent_location_999999")

    def test_geocode_rate_limiting(self):
        """
        Test that 3 rapid consecutive uncached geocode_place calls enforce a minimum 1s gap
        between calls (total time >= 2.0s).
        """
        cache_clear()
        start_time = time.time()

        # Call 3 distinct places rapid-fire so cache isn't hit
        geocode_place("Jaipur, India")
        geocode_place("Delhi, India")
        geocode_place("Mumbai, India")

        elapsed = time.time() - start_time
        self.assertGreaterEqual(
            elapsed, 2.0,
            msg=f"Rate limiting failed: 3 rapid calls took {elapsed:.2f}s (expected >= 2.0s)"
        )

    def test_get_forecast_near_dates(self):
        """Test weather forecast for dates within 16 days (returns actual forecast, is_estimate=False)."""
        cache_clear()
        today = datetime.now().date()
        start_date = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=4)).strftime("%Y-%m-%d")

        res = get_forecast(26.915, 75.818, start_date, end_date)

        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("is_estimate"))
        daily = res.get("daily", [])
        self.assertGreaterEqual(len(daily), 1)

        first_day = daily[0]
        self.assertIn("date", first_day)
        self.assertIn("temp_max", first_day)
        self.assertIn("temp_min", first_day)
        self.assertIn("precipitation_mm", first_day)
        self.assertIn("condition", first_day)

    def test_get_forecast_future_dates(self):
        """Test weather forecast for dates > 16 days out (falls back to climate normals estimate, is_estimate=True)."""
        cache_clear()
        today = datetime.now().date()
        start_date = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=33)).strftime("%Y-%m-%d")

        res = get_forecast(26.915, 75.818, start_date, end_date)

        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("is_estimate"))
        daily = res.get("daily", [])
        self.assertGreaterEqual(len(daily), 1)

        first_day = daily[0]
        self.assertIn("date", first_day)
        self.assertIn("temp_max", first_day)
        self.assertIn("temp_min", first_day)
        self.assertIn("precipitation_mm", first_day)
        self.assertIn("condition", first_day)


if __name__ == "__main__":
    unittest.main()

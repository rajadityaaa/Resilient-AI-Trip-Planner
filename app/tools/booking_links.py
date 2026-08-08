"""
Booking Links Generator: Compiles search handoff links for flights and hotels.
"""
import urllib.parse

def build_hotel_booking_link(hotel_name: str, destination: str) -> str:
    """
    Generate a Booking.com search results link for a given hotel and destination.
    """
    query = f"{hotel_name}, {destination}"
    encoded_query = urllib.parse.quote(query)
    return f"https://www.booking.com/searchresults.html?ss={encoded_query}"

def build_flight_booking_link(origin: str, destination: str, start_date: str, end_date: str) -> str:
    """
    Generate a Google Flights search link between origin and destination on specific dates.
    """
    encoded_origin = urllib.parse.quote(origin)
    encoded_destination = urllib.parse.quote(destination)
    return f"https://www.google.com/travel/flights?q=Flights%20from%20{encoded_origin}%20to%20{encoded_destination}%20on%20{start_date}%20through%20{end_date}"

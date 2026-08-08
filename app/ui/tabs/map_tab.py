"""
Map Tab UI component.
Renders an interactive Folium map showing attractions, restaurants, and hotels.
"""
import streamlit as st
import folium
from streamlit_folium import st_folium
from app.agents.state import TripState
from app.tools.geocode_tools import geocode_place


def render_map_tab(trip_result: TripState):
    """
    Render an interactive map centered on the destination, listing attractions,
    restaurants, and hotels with color-coded markers.
    
    Args:
        trip_result: Completed TripState dict.
    """
    st.subheader("🗺️ Destination Map")

    dest = trip_result.get("destination")
    if not dest:
        st.info("No destination selected yet.")
        return

    # 1. Resolve map center coordinates (using cached geocoding lookup)
    try:
        geo = geocode_place(dest)
        center_lat = geo["lat"]
        center_lon = geo["lon"]
    except Exception:
        # Fallback to a default center or center of available items
        center_lat = 0.0
        center_lon = 0.0

    attractions = trip_result.get("attractions", []) or []
    restaurants = trip_result.get("restaurants", []) or []
    hotels = trip_result.get("hotels", []) or []

    # If center_lat is 0, find first item to center on
    if center_lat == 0.0:
        for item_list in [attractions, restaurants, hotels]:
            if item_list:
                center_lat = float(item_list[0].get("lat", item_list[0].get("location_lat", 0)))
                center_lon = float(item_list[0].get("lon", item_list[0].get("location_lon", 0)))
                break

    # Initialize Folium Map
    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

    # 2. Add Markers for Attractions (Blue)
    for a in attractions:
        lat = a.get("lat")
        lon = a.get("lon")
        name = a.get("name", "Attraction")
        cat = a.get("category", "Attraction")
        if lat is not None and lon is not None:
            popup_text = f"🏰 <b>{name}</b><br>Type: {cat}"
            folium.Marker(
                location=[float(lat), float(lon)],
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=name,
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)

    # 3. Add Markers for Restaurants (Red)
    for r in restaurants:
        lat = r.get("lat")
        lon = r.get("lon")
        name = r.get("name", "Restaurant")
        cat = r.get("category", "Restaurant")
        if lat is not None and lon is not None:
            popup_text = f"🍴 <b>{name}</b><br>Type: {cat}"
            folium.Marker(
                location=[float(lat), float(lon)],
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=name,
                icon=folium.Icon(color="red", icon="cutlery")
            ).add_to(m)

    # 4. Add Markers for Hotels (Green)
    for h in hotels:
        # Remember hotels schema contains location_lat/location_lon or lat/lon
        lat = h.get("location_lat") or h.get("lat")
        lon = h.get("location_lon") or h.get("lon")
        name = h.get("name", "Hotel")
        rating = h.get("star_rating", h.get("rating", "N/A"))
        price = h.get("price_per_night_usd", h.get("price_per_night", "N/A"))
        if lat is not None and lon is not None:
            popup_text = f"🏨 <b>{name}</b><br>Rating: ⭐ {rating}<br>Price: ${price}/night"
            folium.Marker(
                location=[float(lat), float(lon)],
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=name,
                icon=folium.Icon(color="green", icon="home")
            ).add_to(m)

    # Layout: Map on left, Legend / Details on right
    col1, col2 = st.columns([3, 1])

    with col1:
        # Display the map inside Streamlit
        st_folium(m, width=800, height=500, returned_objects=[])

    with col2:
        st.write("### 🔑 Legend")
        
        # Leaflet-style custom Markdown legend table
        st.markdown(
            """
            | Color | Type | Marker Icon |
            | :--- | :--- | :--- |
            | 🔵 **Blue** | Attraction | Info Sign |
            | 🔴 **Red** | Restaurant | Cutlery |
            | 🟢 **Green**| Hotel / Stay | Home |
            """
        )
        
        # Details list counts
        st.write("### 📈 Items Shown")
        st.markdown(f"- 🏰 Attractions: **{len(attractions)}**")
        st.markdown(f"- 🍴 Restaurants: **{len(restaurants)}**")
        st.markdown(f"- 🏨 Hotels: **{len(hotels)}**")

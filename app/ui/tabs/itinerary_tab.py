"""
Itinerary Tab UI component.
Displays day-by-day itinerary inside expanders and provides a PDF download button.
"""
import streamlit as st
from app.agents.state import TripState
from app.tools.pdf_tools import export_itinerary_pdf
from app.tools.booking_links import build_hotel_booking_link, build_flight_booking_link


def render_itinerary_tab(trip_result: TripState):
    """
    Render the day-by-day itinerary tab with expanders and export tools.
    
    Args:
        trip_result: Completed TripState dict.
    """
    itinerary = trip_result.get("daily_itinerary", [])
    
    if not itinerary:
        st.info("No itinerary data available.")
        return

    # PDF Export Actions
    st.subheader("📅 Detailed Itinerary")
    
    # Render PDF export button
    try:
        pdf_bytes = export_itinerary_pdf(trip_result)
        dest_name = trip_result.get("destination", "Trip")
        file_name = f"Itinerary_{dest_name.replace(' ', '_')}.pdf"
        
        st.download_button(
            label="📥 Export Itinerary as PDF",
            data=pdf_bytes,
            file_name=file_name,
            mime="application/pdf",
            help="Download a clean PDF copy of your travel itinerary."
        )
    except Exception as e:
        st.error(f"Could not generate PDF export: {e}")

    # ── "Book This Trip" Section ──
    st.write("---")
    st.markdown("### 🛍️ Book This Trip")
    st.caption("These links take you to Booking.com and Google Flights to search and complete your booking directly — this app does not process payments or hold live inventory.")
    
    flight_link = build_flight_booking_link(
        origin=trip_result.get("origin", "Delhi"),
        destination=trip_result.get("destination", "Bangkok"),
        start_date=trip_result.get("start_date", ""),
        end_date=trip_result.get("end_date", "")
    )
    st.link_button("✈️ Search Flights on Google Flights", flight_link)
    
    hotels = trip_result.get("hotels") or []
    if hotels:
        st.write("")
        st.write("**Recommended Accommodations:**")
        top_hotels = sorted(
            hotels, 
            key=lambda h: (-float(h.get("star_rating", 0.0)), float(h.get("price_per_night_usd", 9999.0)))
        )[:3]
        
        h_cols = st.columns(len(top_hotels))
        for idx, col in enumerate(h_cols):
            hotel = top_hotels[idx]
            h_name = hotel.get("name", "Unknown Hotel")
            h_price = hotel.get("price_per_night_usd", 0.0)
            h_rating = hotel.get("star_rating", 0.0)
            h_link = build_hotel_booking_link(h_name, trip_result.get("destination", ""))
            
            with col:
                st.markdown(
                    f"""
                    <div style="background-color:#182235; padding:15px; border-radius:12px; border:1px solid rgba(255,255,255,0.08); margin-bottom:10px;">
                        <div style="font-weight:600; font-family:'Poppins', sans-serif; color:#F8FAFC; font-size:0.95rem; margin-bottom:5px; height: 40px; overflow: hidden; text-overflow: ellipsis;">{h_name}</div>
                        <div style="color:#94A3B8; font-size:0.8rem; margin-bottom:2px;">⭐ {h_rating} Rating</div>
                        <div style="color:#F59E0B; font-weight:700; font-size:0.9rem; margin-bottom:10px;">${h_price:,.2f} / night</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.link_button("🏨 Search & Book on Booking.com", h_link, key=f"hotel_lnk_{idx}")
                
    st.write("---")

    # Display each day as an expander
    circle_numbers = {1: "❶", 2: "❷", 3: "❸", 4: "❹", 5: "❺", 6: "❻", 7: "❼", 8: "❽", 9: "❾", 10: "❿"}
    for day in itinerary:
        day_num = day.get("day", "?")
        day_date = day.get("date", "?")
        
        try:
            badge = circle_numbers.get(int(day_num), "🗓️")
        except ValueError:
            badge = "🗓️"
            
        expander_title = f"{badge} Day {day_num} — {day_date}"

        with st.expander(expander_title, expanded=(day_num == 1)):
            st.markdown('<div class="itinerary-section-header">🌅 Morning</div>', unsafe_allow_html=True)
            st.write(day.get("morning", "Free time/exploring."))

            st.markdown('<div class="itinerary-section-header">☀️ Afternoon</div>', unsafe_allow_html=True)
            st.write(day.get("afternoon", "Free time/exploring."))

            st.markdown('<div class="itinerary-section-header">🌌 Evening</div>', unsafe_allow_html=True)
            st.write(day.get("evening", "Leisure / return to hotel."))

            notes = day.get("notes", "")
            if notes:
                st.info(f"💡 **Day {day_num} Notes & Reminders:**\n{notes}")

/**
 * map.js - Lazy-Loaded & Robust Leaflet Map with Custom Marker Badges and OpenStreetMap Credit
 */

import { el } from "./utils.js";

export class MapManager {
  constructor(containerId = "map-view") {
    this.containerId = containerId;
    this.map = null;
    this.markersGroup = null;
    this.markers = [];
    this.currentTrip = null;
    this.destinationCenter = null;
  }

  async initMap(trip) {
    this.currentTrip = trip;
    const container = document.getElementById(this.containerId);
    if (!container) return;

    if (!window.L) {
      // If Leaflet script is still defer-loading, give it a moment
      for (let i = 0; i < 10; i++) {
        if (window.L) break;
        await new Promise((r) => setTimeout(r, 100));
      }
      if (!window.L) {
        this.renderFallbackList(container, trip);
        return;
      }
    }

    const L = window.L;

    // Fix Leaflet's default image icon paths to use local vendor assets
    if (L.Icon?.Default?.prototype) {
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "vendor/leaflet/images/marker-icon-2x.png",
        iconUrl: "vendor/leaflet/images/marker-icon.png",
        shadowUrl: "vendor/leaflet/images/marker-shadow.png",
      });
    }

    if (this.map) {
      try {
        this.map.remove();
      } catch (err) {
        console.warn("Leaflet map cleanup warning:", err);
      }
      this.map = null;
    }

    // Default initial center
    this.map = L.map(this.containerId, {
      scrollWheelZoom: false,
      zoomControl: true,
    }).setView([20, 0], 2);

    // OpenStreetMap tile layer with attribution
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(this.map);

    this.markersGroup = L.featureGroup().addTo(this.map);
    this.plotPlaces(trip);

    // If the map container is already visible in the DOM, fit bounds immediately
    if (container.offsetWidth > 0 && container.offsetHeight > 0) {
      requestAnimationFrame(() => {
        this.map?.invalidateSize({ pan: false });
        this.fitToMarkers();
      });
    }
  }

  plotPlaces(trip) {
    if (!this.map || !window.L || !this.markersGroup) return;
    const L = window.L;
    this.markersGroup.clearLayers();
    this.markers = [];

    const attractions = trip.attractions || [];
    const restaurants = trip.restaurants || [];
    const hotels = trip.hotels || [];

    // 1. Identify destination center from items with valid coordinates (strictly excluding 0,0)
    this.destinationCenter = null;
    const allCandidates = [...attractions, ...restaurants, ...hotels];
    for (const item of allCandidates) {
      const lat = Number(item.lat ?? item.latitude ?? item.location_lat);
      const lon = Number(item.lon ?? item.longitude ?? item.location_lng ?? item.location_lon);
      if (
        !isNaN(lat) &&
        !isNaN(lon) &&
        !(lat === 0 && lon === 0) &&
        Math.abs(lat) <= 90 &&
        Math.abs(lon) <= 180
      ) {
        this.destinationCenter = [lat, lon];
        break;
      }
    }

    // 2. Icon factory with clear distinctive styling
    const createIcon = (colorHex, letter) => {
      return L.divIcon({
        className: "custom-map-marker",
        html: `<div style="background-color:${colorHex}; width:24px; height:24px; border-radius:50%; border:2px solid #ffffff; box-shadow:0 3px 8px rgba(0,0,0,0.65); display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:800; color:#ffffff; font-family:'Plus Jakarta Sans',sans-serif;">${letter}</div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
        popupAnchor: [0, -12],
      });
    };

    const iconAttraction = createIcon("#38bdf8", "A"); // Cyan Blue for Attractions
    const iconRestaurant = createIcon("#f97316", "R"); // Warm Orange for Food
    const iconHotel = createIcon("#a855f7", "H");      // Royal Purple for Hotels

    const addMarker = (place, type, icon, idx) => {
      let lat = Number(place.lat ?? place.latitude ?? place.location_lat);
      let lon = Number(place.lon ?? place.longitude ?? place.location_lng ?? place.location_lon);
      let isEstimated = false;

      // Filter out invalid or Null Island (0,0) coordinates
      if (
        isNaN(lat) ||
        isNaN(lon) ||
        (lat === 0 && lon === 0) ||
        Math.abs(lat) > 90 ||
        Math.abs(lon) > 180
      ) {
        if (this.destinationCenter) {
          // Jitter slightly around destination center so place is represented near other sites
          const angle = idx * 1.37;
          const dist = 0.003 + (idx % 4) * 0.0015;
          lat = this.destinationCenter[0] + dist * Math.cos(angle);
          lon = this.destinationCenter[1] + dist * Math.sin(angle);
          isEstimated = true;
        } else {
          return;
        }
      }

      const marker = L.marker([lat, lon], { icon }).addTo(this.markersGroup);

      const isAi = place.source === "ai_suggested" || isEstimated;
      const badgeHtml = isAi
        ? '<span style="background:rgba(168,85,247,0.15);color:#c084fc;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;">Curated</span>'
        : '<span style="background:rgba(56,189,248,0.15);color:#38bdf8;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;">Verified</span>';

      const catText = place.category || place.cuisine || type;
      const rating = place.rating || place.star_rating;
      const ratingHtml = rating ? `<span style="font-size:11px; color:#f59e0b; margin-left:6px; font-weight:600;">⭐ ${rating}</span>` : "";
      const price = place.price_per_night_usd;
      const priceHtml = price ? `<div style="font-size:11px; color:#10b981; font-weight:700; margin-top:3px;">$${price}/night</div>` : "";

      const popupHtml = `
        <div style="font-family:'Manrope',sans-serif; color:#0f172a; padding:6px 2px; min-width:180px; max-width:240px;">
          <div style="font-weight:700; font-size:13px; margin-bottom:3px; color:#0f172a; line-height:1.3;">${place.name || type}</div>
          <div style="font-size:11px; color:#64748b; margin-bottom:6px; display:flex; align-items:center;">
            <span>${catText}</span>${ratingHtml}
          </div>
          <div style="margin-bottom:6px;">${badgeHtml}</div>
          ${priceHtml}
          ${place.match_reason ? `<div style="font-size:11px; color:#334155; line-height:1.3; border-top:1px solid #e2e8f0; padding-top:4px; margin-top:4px;">${place.match_reason}</div>` : ""}
        </div>
      `;

      marker.bindPopup(popupHtml);
      this.markers.push({ name: place.name, type, marker });
    };

    attractions.forEach((p, i) => addMarker(p, "Attraction", iconAttraction, i));
    restaurants.forEach((p, i) => addMarker(p, "Restaurant", iconRestaurant, i));
    hotels.forEach((p, i) => addMarker(p, "Hotel", iconHotel, i));

    this.fitToMarkers();
  }

  fitToMarkers() {
    if (!this.map || !this.markersGroup) return;

    if (this.markers.length > 1) {
      try {
        const bounds = this.markersGroup.getBounds();
        if (bounds.isValid()) {
          this.map.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
        }
      } catch (err) {
        console.warn("fitBounds failed:", err);
      }
    } else if (this.markers.length === 1) {
      try {
        this.map.setView(this.markers[0].marker.getLatLng(), 14);
      } catch {
        // ignore
      }
    } else if (this.destinationCenter) {
      this.map.setView(this.destinationCenter, 13);
    }
  }

  /**
   * Called whenever the user switches to the Map Overview tab.
   * Forces Leaflet container resize calculation and re-centers view properly.
   */
  onTabVisible() {
    if (!this.map) {
      if (this.currentTrip) {
        this.initMap(this.currentTrip);
      }
      return;
    }

    // Double tick to handle CSS display:block + opacity transition
    requestAnimationFrame(() => {
      this.map.invalidateSize({ pan: false });
      this.fitToMarkers();
    });

    setTimeout(() => {
      if (this.map) {
        this.map.invalidateSize({ pan: false });
        this.fitToMarkers();
      }
    }, 120);
  }

  renderFallbackList(container, trip) {
    container.innerHTML = "";
    const list = el("div", { style: "padding: 24px; color: var(--color-text-secondary);" }, [
      el("p", { style: "margin-bottom: 12px; color: var(--color-accent-light);" }, "Map preview currently unavailable. Listing places:"),
      el("ul", { style: "list-style: disc; padding-left: 20px;" }, [
        ...(trip.attractions || []).map(a => el("li", {}, a.name)),
        ...(trip.restaurants || []).map(r => el("li", {}, r.name)),
        ...(trip.hotels || []).map(h => el("li", {}, h.name)),
      ]),
    ]);
    container.appendChild(list);
  }
}

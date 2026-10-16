/**
 * map.js - Lazy-Loaded Leaflet Map with Custom Marker Badges and OpenStreetMap Credit
 */

import { el, sanitizeUrl } from "./utils.js";

let leafletLoaded = false;
let leafletLoadingPromise = null;

/**
 * Dynamically load vendored Leaflet CSS and JS on demand.
 */
function loadLeafletVendor() {
  if (leafletLoaded) return Promise.resolve();
  if (leafletLoadingPromise) return leafletLoadingPromise;

  leafletLoadingPromise = new Promise((resolve, reject) => {
    // Add Leaflet CSS
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "vendor/leaflet/leaflet.css";
    document.head.appendChild(link);

    // Add Leaflet JS
    const script = document.createElement("script");
    script.src = "vendor/leaflet/leaflet.js";
    script.onload = () => {
      leafletLoaded = true;
      // Fix Leaflet's default image icon paths to use local vendor assets
      if (window.L) {
        delete window.L.Icon.Default.prototype._getIconUrl;
        window.L.Icon.Default.mergeOptions({
          iconRetinaUrl: "vendor/leaflet/images/marker-icon-2x.png",
          iconUrl: "vendor/leaflet/images/marker-icon.png",
          shadowUrl: "vendor/leaflet/images/marker-shadow.png",
        });
      }
      resolve();
    };
    script.onerror = () => reject(new Error("Failed to load vendored Leaflet library."));
    document.body.appendChild(script);
  });

  return leafletLoadingPromise;
}

export class MapManager {
  constructor(containerId = "map-view") {
    this.containerId = containerId;
    this.map = null;
    this.markersGroup = null;
    this.markers = [];
  }

  async initMap(trip) {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    try {
      await loadLeafletVendor();
    } catch (err) {
      this.renderFallbackList(container, trip);
      return;
    }

    if (!window.L) {
      this.renderFallbackList(container, trip);
      return;
    }

    if (this.map) {
      this.map.remove();
      this.map = null;
    }

    // Default center
    const L = window.L;
    this.map = L.map(this.containerId, {
      scrollWheelZoom: false,
    }).setView([20, 0], 2);

    // OpenStreetMap tile layer with attribution
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(this.map);

    this.markersGroup = L.featureGroup().addTo(this.map);
    this.plotPlaces(trip);

    // Force map redraw in case tab was hidden during load
    setTimeout(() => {
      this.map?.invalidateSize();
    }, 250);
  }

  plotPlaces(trip) {
    if (!this.map || !window.L) return;
    const L = window.L;
    this.markersGroup.clearLayers();
    this.markers = [];

    const attractions = trip.attractions || [];
    const restaurants = trip.restaurants || [];
    const hotels = trip.hotels || [];

    const createIcon = (colorHex) => {
      return L.divIcon({
        className: "custom-map-marker",
        html: `<div style="background-color: ${colorHex}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid #ffffff; box-shadow: 0 2px 6px rgba(0,0,0,0.6);"></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      });
    };

    const iconAttraction = createIcon("#38bdf8"); // Blue
    const iconRestaurant = createIcon("#f97316"); // Orange
    const iconHotel = createIcon("#a855f7");      // Purple

    const addMarker = (place, type, icon) => {
      const lat = Number(place.lat);
      const lon = Number(place.lon);
      if (isNaN(lat) || isNaN(lon)) return;

      const marker = L.marker([lat, lon], { icon }).addTo(this.markersGroup);

      const isAi = place.source === "ai_suggested";
      const badgeHtml = isAi ? '<span style="background:rgba(168,85,247,0.15);color:#c084fc;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600;">AI-suggested</span>' : '';
      const catText = place.category || place.cuisine || type;

      const popupHtml = `
        <div style="font-family:'Manrope',sans-serif; color:#0f172a; padding:4px 0; max-width:220px;">
          <div style="font-weight:700; font-size:13px; margin-bottom:2px;">${place.name || "Place"}</div>
          <div style="font-size:11px; color:#64748b; margin-bottom:4px;">${catText} ${badgeHtml}</div>
          ${place.match_reason ? `<div style="font-size:11px; color:#334155; line-height:1.3;">${place.match_reason}</div>` : ""}
        </div>
      `;

      marker.bindPopup(popupHtml);
      this.markers.push({ name: place.name, marker });
    };

    attractions.forEach(p => addMarker(p, "Attraction", iconAttraction));
    restaurants.forEach(p => addMarker(p, "Restaurant", iconRestaurant));
    hotels.forEach(p => addMarker(p, "Hotel", iconHotel));

    if (this.markers.length > 0) {
      try {
        this.map.fitBounds(this.markersGroup.getBounds(), { padding: [40, 40], maxZoom: 14 });
      } catch {
        // bounds fit issue
      }
    }
  }

  renderFallbackList(container, trip) {
    container.innerHTML = "";
    const list = el("div", { style: "padding: 24px; color: var(--color-text-secondary);" }, [
      el("p", { style: "margin-bottom: 12px; color: var(--color-accent-light);" }, "Map preview currently unavailable. Listing places:"),
      el("ul", { style: "list-style: disc; padding-left: 20px;" }, [
        ...(trip.attractions || []).map(a => el("li", {}, a.name)),
        ...(trip.restaurants || []).map(r => el("li", {}, r.name)),
      ]),
    ]);
    container.appendChild(list);
  }
}

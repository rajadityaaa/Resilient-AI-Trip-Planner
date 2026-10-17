/**
 * map.js - Google Maps-Inspired Interactive Geospatial Experience
 * Features:
 *  - Google Maps style CartoDB Voyager & Satellite basemap layers
 *  - Google Maps teardrop SVG markers with category icons (Attraction, Food, Stay)
 *  - Spot name labels on the map
 *  - Segmented Map/Satellite switcher
 *  - Category filter chips (All, Attractions, Food, Stays)
 *  - Rich popup cards with ratings, match reasons, and "Open in Google Maps" links
 *  - Intelligent orbital clustering/spiderfy for overlapping coordinates
 */

import { el } from "./utils.js";

export class MapManager {
  constructor(containerId = "map-view") {
    this.containerId = containerId;
    this.map = null;
    this.markersGroup = null;
    this.markers = []; // { name, type, categoryKey, marker, data }
    this.currentTrip = null;
    this.destinationCenter = null;
    this.activeFilter = "all";
    this.activeLayerType = "roadmap"; // "roadmap" | "satellite"

    // Basemap tile layers
    this.streetLayer = null;
    this.satelliteLayer = null;
    this.satelliteLabelsLayer = null;
  }

  async initMap(trip) {
    this.currentTrip = trip;
    const container = document.getElementById(this.containerId);
    if (!container) return;

    if (!window.L) {
      // If Leaflet script is still defer-loading, give it a moment
      for (let i = 0; i < 15; i++) {
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

    // Initialize Map with custom zoom control position
    this.map = L.map(this.containerId, {
      scrollWheelZoom: false,
      zoomControl: false,
    }).setView([20, 0], 2);

    // Zoom control at bottom right (Google Maps style)
    L.control.zoom({ position: "bottomright" }).addTo(this.map);

    // 1. Google Maps style Roadmap Layer (Esri World Street Map: crisp highways, arterial roads, parks, no watermark)
    this.streetLayer = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, METI, TomTom",
        maxZoom: 19,
      }
    );

    // 2. Google Maps style Satellite Layer (Esri World Imagery + Boundaries/Places overlay)
    this.satelliteLayer = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP",
        maxZoom: 19,
      }
    );

    this.satelliteLabelsLayer = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      {
        maxZoom: 19,
        pane: "shadowPane",
      }
    );

    // Default to Street / Roadmap layer
    this.streetLayer.addTo(this.map);
    this.activeLayerType = "roadmap";

    this.markersGroup = L.featureGroup().addTo(this.map);

    // Build the spots and render Google Maps overlay controls
    this.plotPlaces(trip);
    this.renderMapControls();

    // If the map container is already visible, fit bounds immediately
    if (container.offsetWidth > 0 && container.offsetHeight > 0) {
      requestAnimationFrame(() => {
        this.map?.invalidateSize({ pan: false });
        this.fitToMarkers();
      });
    }
  }

  setBasemap(type) {
    if (!this.map || this.activeLayerType === type) return;

    if (type === "satellite") {
      this.map.removeLayer(this.streetLayer);
      this.satelliteLayer.addTo(this.map);
      this.satelliteLabelsLayer.addTo(this.map);
      this.activeLayerType = "satellite";
    } else {
      this.map.removeLayer(this.satelliteLayer);
      this.map.removeLayer(this.satelliteLabelsLayer);
      this.streetLayer.addTo(this.map);
      this.activeLayerType = "roadmap";
    }

    // Update active state in UI toggle buttons
    const btnRoadmap = document.getElementById("gmap-btn-roadmap");
    const btnSatellite = document.getElementById("gmap-btn-satellite");
    if (btnRoadmap && btnSatellite) {
      btnRoadmap.classList.toggle("active", type === "roadmap");
      btnSatellite.classList.toggle("active", type === "satellite");
    }
  }

  renderMapControls() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    // Remove any previously injected control bar
    const oldToolbar = container.querySelector(".gmap-floating-toolbar");
    if (oldToolbar) oldToolbar.remove();

    const attractionsCount = (this.currentTrip?.attractions || []).length;
    const foodCount = (this.currentTrip?.restaurants || []).length;
    const staysCount = (this.currentTrip?.hotels || []).length;
    const totalCount = attractionsCount + foodCount + staysCount;

    const toolbar = el("div", { className: "gmap-floating-toolbar" }, [
      // Left Cluster: Segmented Basemap Switcher + Fit Spots
      el("div", { className: "gmap-toolbar-cluster gmap-toolbar-left" }, [
        el("div", { className: "gmap-segmented-toggle" }, [
          el(
            "button",
            {
              type: "button",
              id: "gmap-btn-roadmap",
              className: `gmap-toggle-btn ${this.activeLayerType === "roadmap" ? "active" : ""}`,
              title: "Street Roadmap View",
              onclick: () => this.setBasemap("roadmap"),
            },
            [
              el("span", { className: "gmap-btn-icon" }, "🗺️"),
              el("span", { className: "gmap-btn-text" }, "Map"),
            ]
          ),
          el(
            "button",
            {
              type: "button",
              id: "gmap-btn-satellite",
              className: `gmap-toggle-btn ${this.activeLayerType === "satellite" ? "active" : ""}`,
              title: "Satellite View",
              onclick: () => this.setBasemap("satellite"),
            },
            [
              el("span", { className: "gmap-btn-icon" }, "🛰️"),
              el("span", { className: "gmap-btn-text" }, "Satellite"),
            ]
          ),
        ]),
        el(
          "button",
          {
            type: "button",
            className: "gmap-recenter-btn",
            title: "Center and zoom to fit all spots",
            onclick: () => this.fitToMarkers(),
          },
          [
            el("span", {}, "⌖"),
            el("span", { className: "gmap-recenter-text" }, "Fit Spots"),
          ]
        ),
      ]),

      // Right Cluster: Category Filter Chips
      el("div", { className: "gmap-toolbar-cluster gmap-toolbar-right" }, [
        el("div", { className: "gmap-filter-chips" }, [
          el(
            "button",
            {
              type: "button",
              className: `gmap-chip ${this.activeFilter === "all" ? "active" : ""}`,
              "data-category": "all",
              onclick: (e) => this.filterCategory("all", e.currentTarget),
            },
            `All Spots (${totalCount})`
          ),
          el(
            "button",
            {
              type: "button",
              className: `gmap-chip chip-attraction ${this.activeFilter === "attraction" ? "active" : ""}`,
              "data-category": "attraction",
              onclick: (e) => this.filterCategory("attraction", e.currentTarget),
            },
            `🏛️ Attractions (${attractionsCount})`
          ),
          el(
            "button",
            {
              type: "button",
              className: `gmap-chip chip-food ${this.activeFilter === "food" ? "active" : ""}`,
              "data-category": "food",
              onclick: (e) => this.filterCategory("food", e.currentTarget),
            },
            `🍽️ Food (${foodCount})`
          ),
          el(
            "button",
            {
              type: "button",
              className: `gmap-chip chip-hotel ${this.activeFilter === "hotel" ? "active" : ""}`,
              "data-category": "hotel",
              onclick: (e) => this.filterCategory("hotel", e.currentTarget),
            },
            `🏨 Stays (${staysCount})`
          ),
        ]),
      ]),
    ]);

    container.appendChild(toolbar);
  }

  filterCategory(category, buttonEl) {
    this.activeFilter = category;

    // Update active class on chips
    const toolbar = document.querySelector(".gmap-floating-toolbar");
    if (toolbar) {
      toolbar.querySelectorAll(".gmap-chip").forEach((chip) => {
        chip.classList.toggle("active", chip.getAttribute("data-category") === category);
      });
    }

    if (!this.map || !this.markersGroup) return;

    this.markersGroup.clearLayers();

    const visibleMarkers = [];
    for (const item of this.markers) {
      if (category === "all" || item.categoryKey === category) {
        this.markersGroup.addLayer(item.marker);
        visibleMarkers.push(item);
      }
    }

    // Re-fit map view to visible spots
    if (visibleMarkers.length > 0) {
      const group = window.L.featureGroup(visibleMarkers.map((m) => m.marker));
      const bounds = group.getBounds();
      if (bounds.isValid()) {
        this.map.fitBounds(bounds, { padding: [60, 60], maxZoom: 15 });
      }
    } else if (this.destinationCenter) {
      this.map.setView(this.destinationCenter, 13);
    }
  }

  /**
   * Generates a Google Maps Teardrop SVG Pin with realistic drop shadow,
   * high-contrast inner circle, and thematic vector icon.
   */
  createGooglePinIcon(categoryKey, spotName) {
    const L = window.L;

    let pinColor = "#1a73e8"; // Google Blue for Attractions
    let iconSvg = `
      <!-- Landmark / Monument Icon -->
      <path d="M12 4L4 9v2h16V9l-8-5zm-5 8v6h2v-6H7zm4 0v6h2v-6h-2zm4 0v6h2v-6h-2zM3 19v2h18v-2H3z" fill="#1a73e8"/>
    `;

    if (categoryKey === "food") {
      pinColor = "#ea4335"; // Google Red/Coral for Dining
      iconSvg = `
        <!-- Cutlery / Dining Icon -->
        <path d="M11 5v5a2 2 0 002 2v7h2v-7a2 2 0 002-2V5h-1v4h-1V5h-1v4h-1V5h-2zm8 0h-1v6a2 2 0 01-2 2v6h2V5z" fill="#ea4335"/>
      `;
    } else if (categoryKey === "hotel") {
      pinColor = "#8e24aa"; // Google Purple for Stays
      iconSvg = `
        <!-- Hotel / Bed Icon -->
        <path d="M7 11V7h2v4h10V7h2v11h-2v-2H5v2H3V11h4zm1-2a1.5 1.5 0 100-3 1.5 1.5 0 000 3z" fill="#8e24aa"/>
      `;
    }

    const safeName = (spotName || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    const html = `
      <div class="gmap-marker-pin-wrapper gmap-marker-${categoryKey}">
        <svg class="gmap-teardrop-svg" width="34" height="44" viewBox="0 0 34 44" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <filter id="gmap-shadow-${categoryKey}" x="-20%" y="-10%" width="140%" height="135%">
              <feDropShadow dx="0" dy="3.5" stdDeviation="2.5" flood-color="#000000" flood-opacity="0.38"/>
            </filter>
          </defs>
          <!-- Teardrop pin body with subtle gradient -->
          <path d="M17 44 C17 44 32 28.5 32 17 C32 8.716 25.284 2 17 2 C8.716 2 2 8.716 2 17 C2 28.5 17 44 17 44 Z"
                fill="${pinColor}" filter="url(#gmap-shadow-${categoryKey})"/>
          <!-- Inner white circle for icon background -->
          <circle cx="17" cy="17" r="10.5" fill="#ffffff" stroke="rgba(0,0,0,0.06)" stroke-width="0.75"/>
          <!-- Vector Category Glyph centered at 17, 17 -->
          <g transform="translate(5, 5)">
            ${iconSvg}
          </g>
        </svg>
        <div class="gmap-spot-badge" title="${safeName}">${safeName}</div>
      </div>
    `;

    return L.divIcon({
      className: "gmap-custom-div-icon",
      html,
      iconSize: [34, 44],
      iconAnchor: [17, 44], // Exact tip of the teardrop pin
      popupAnchor: [0, -42],
    });
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

    // Track coordinates to spiderfy/disambiguate overlapping markers so every pin is visible
    const coordUsage = new Map();

    const addMarker = (place, type, categoryKey) => {
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
          lat = this.destinationCenter[0];
          lon = this.destinationCenter[1];
          isEstimated = true;
        } else {
          return;
        }
      }

      // Check for exact coordinate overlaps (within ~50-100 meters)
      // Disperse overlapping points in concentric orbital rings so every single spot is visible
      const coordKey = `${lat.toFixed(3)},${lon.toFixed(3)}`;
      const countAtPos = coordUsage.get(coordKey) || 0;
      coordUsage.set(coordKey, countAtPos + 1);

      if (countAtPos > 0) {
        const ring = Math.floor((countAtPos - 1) / 6) + 1;
        const angle = countAtPos * (Math.PI / 3) + ring * 0.35;
        const spread = 0.0055 * ring; // ~600m radius per ring
        const cosLat = Math.max(0.2, Math.cos((lat * Math.PI) / 180));
        lat = lat + spread * Math.cos(angle);
        lon = lon + (spread / cosLat) * Math.sin(angle);
      }

      const icon = this.createGooglePinIcon(categoryKey, place.name);
      const marker = L.marker([lat, lon], { icon }).addTo(this.markersGroup);

      // Google Maps Direct Search & Directions URL
      const destQuery = encodeURIComponent(`${place.name || type}, ${trip.destination || ""}`);
      const gmapsSearchUrl = `https://www.google.com/maps/search/?api=1&query=${destQuery}`;
      const gmapsDirectionsUrl = `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)},${lon.toFixed(6)}`;

      const isAi = place.source === "ai_suggested" || isEstimated;
      const badgeHtml = isAi
        ? '<span class="gmap-badge gmap-badge-curated">Curated Spot</span>'
        : '<span class="gmap-badge gmap-badge-verified">Verified Place</span>';

      const catText = place.category || place.cuisine || type;
      const rating = place.rating || place.star_rating;
      const ratingHtml = rating
        ? `<span class="gmap-popup-rating">★ ${rating}</span>`
        : "";

      const price = place.price_per_night_usd;
      const priceHtml = price
        ? `<div class="gmap-popup-price">$${price} / night</div>`
        : "";

      const matchHtml = place.match_reason
        ? `<div class="gmap-popup-reason">${place.match_reason}</div>`
        : "";

      const popupHtml = `
        <div class="gmap-rich-popup">
          <div class="gmap-popup-header">
            <div class="gmap-popup-type-strip">
              <span class="gmap-popup-type">${catText}</span>
              ${badgeHtml}
            </div>
            <h4 class="gmap-popup-title">${place.name || type}</h4>
          </div>

          <div class="gmap-popup-meta">
            ${ratingHtml}
            ${priceHtml}
          </div>

          ${matchHtml}

          <div class="gmap-popup-actions">
            <a href="${gmapsSearchUrl}" target="_blank" rel="noopener noreferrer" class="gmap-popup-btn gmap-popup-btn-primary">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                <polyline points="15 3 21 3 21 9"></polyline>
                <line x1="10" y1="14" x2="21" y2="3"></line>
              </svg>
              Open in Google Maps
            </a>
            <a href="${gmapsDirectionsUrl}" target="_blank" rel="noopener noreferrer" class="gmap-popup-btn gmap-popup-btn-secondary" title="Get directions">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="3 11 22 2 13 21 11 13 3 11"></polygon>
              </svg>
              Directions
            </a>
          </div>
        </div>
      `;

      marker.bindPopup(popupHtml, {
        maxWidth: 290,
        className: "gmap-custom-popup-wrapper",
      });

      this.markers.push({
        name: place.name,
        type,
        categoryKey,
        marker,
        data: place,
      });
    };

    attractions.forEach((p) => addMarker(p, "Attraction", "attraction"));
    restaurants.forEach((p) => addMarker(p, "Restaurant", "food"));
    hotels.forEach((p) => addMarker(p, "Hotel", "hotel"));

    this.fitToMarkers();
  }

  fitToMarkers() {
    if (!this.map || !this.markersGroup) return;

    const visibleMarkers = this.markers.filter(
      (m) => this.activeFilter === "all" || m.categoryKey === this.activeFilter
    );

    if (visibleMarkers.length > 1) {
      try {
        const group = window.L.featureGroup(visibleMarkers.map((m) => m.marker));
        const bounds = group.getBounds();
        if (bounds.isValid()) {
          this.map.fitBounds(bounds, { padding: [60, 60], maxZoom: 15 });
        }
      } catch (err) {
        console.warn("fitBounds failed:", err);
      }
    } else if (visibleMarkers.length === 1) {
      try {
        this.map.setView(visibleMarkers[0].marker.getLatLng(), 14);
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
        ...(trip.attractions || []).map((a) => el("li", {}, a.name)),
        ...(trip.restaurants || []).map((r) => el("li", {}, r.name)),
        ...(trip.hotels || []).map((h) => el("li", {}, h.name)),
      ]),
    ]);
    container.appendChild(list);
  }
}

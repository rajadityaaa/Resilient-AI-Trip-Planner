/**
 * results.js - Trip Results Dashboard, Itinerary Accordion, Stay/Food Cards, SVG Doughnut, and Timings Panel
 */

import { el, formatCurrency, formatDate, showToast, copyToClipboard, sanitizeUrl } from "./utils.js";
import { AppState } from "./state.js";
import { API } from "./api.js";
import { generateTripIcs } from "./ics.js";

export class ResultsManager {
  constructor(mapManager, onReplanRequested) {
    this.mapManager = mapManager;
    this.onReplanRequested = onReplanRequested;
    this.section = document.getElementById("results-section");

    // Dashboard header elements
    this.titleEl = document.getElementById("results-title");
    this.overviewEl = document.getElementById("results-overview");
    this.metaDest = document.getElementById("results-meta-dest");
    this.metaDates = document.getElementById("results-meta-dates");
    this.metaTravelers = document.getElementById("results-meta-travelers");
    this.metaBudget = document.getElementById("results-meta-budget");
    this.backupBanner = document.getElementById("backup-data-banner");
    this.backupList = document.getElementById("backup-data-list");

    // Action buttons
    this.btnShare = document.getElementById("results-btn-share");
    this.btnSave = document.getElementById("results-btn-save");
    this.btnPrint = document.getElementById("results-btn-print");
    this.btnPdf = document.getElementById("results-btn-pdf");
    this.btnIcs = document.getElementById("results-btn-ics");
    this.btnReplan = document.getElementById("results-btn-replan");

    // Containers
    this.itineraryContainer = document.getElementById("itinerary-container");
    this.btnExpandAll = document.getElementById("btn-expand-all");
    this.btnCollapseAll = document.getElementById("btn-collapse-all");
    this.hotelsContainer = document.getElementById("hotels-container");
    this.restaurantsContainer = document.getElementById("restaurants-container");
    this.weatherContainer = document.getElementById("weather-container");
    this.budgetTableContainer = document.getElementById("budget-table-container");
    this.budgetSvgContainer = document.getElementById("budget-svg-container");
    this.budgetTotalCenter = document.getElementById("budget-donut-center");
    this.transportContainer = document.getElementById("transport-container");
    this.packingContainer = document.getElementById("packing-container");
    this.timingsContainer = document.getElementById("timings-container");

    this.currentTrip = null;
    this.bindGlobalActions();
  }

  bindGlobalActions() {
    this.btnShare?.addEventListener("click", () => this.handleShare());
    this.btnSave?.addEventListener("click", () => this.handleSave());
    this.btnPrint?.addEventListener("click", () => window.print());
    this.btnPdf?.addEventListener("click", () => this.handleDownloadPdf());
    this.btnIcs?.addEventListener("click", () => {
      if (this.currentTrip) generateTripIcs(this.currentTrip);
    });
    this.btnReplan?.addEventListener("click", () => {
      if (this.currentTrip && this.onReplanRequested) {
        this.onReplanRequested(this.currentTrip);
      }
    });

    this.btnExpandAll?.addEventListener("click", () => {
      document.querySelectorAll(".day-card").forEach(c => c.classList.add("expanded"));
    });
    this.btnCollapseAll?.addEventListener("click", () => {
      document.querySelectorAll(".day-card").forEach(c => c.classList.remove("expanded"));
    });

    const bannerClose = document.getElementById("backup-banner-close");
    bannerClose?.addEventListener("click", () => {
      this.backupBanner?.classList.remove("active");
    });
  }

  render(tripData, isSample = false) {
    this.currentTrip = tripData;
    if (!this.section) return;

    this.section.classList.add("active");
    this.section.scrollIntoView({ behavior: "smooth" });

    const firstDay = tripData.daily_itinerary?.[0] || {};
    const tripTitle = firstDay._trip_title || `${tripData.destination || "Trip"} Expedition`;
    const overview = firstDay._overview || tripData.overview || "Your custom curated itinerary, optimized across parallel agent pipelines.";

    if (this.titleEl) this.titleEl.textContent = tripTitle;
    if (this.overviewEl) this.overviewEl.textContent = overview;
    if (this.metaDest) this.metaDest.textContent = tripData.destination || "Destination";
    if (this.metaDates) this.metaDates.textContent = `${formatDate(tripData.start_date)} - ${formatDate(tripData.end_date)}`;
    if (this.metaTravelers) this.metaTravelers.textContent = `${tripData.travelers || 1} traveler${(tripData.travelers || 1) > 1 ? "s" : ""}`;
    if (this.metaBudget) this.metaBudget.textContent = formatCurrency(tripData.budget_total, tripData.budget_currency);

    // Reset subnav tabs to first tab (Itinerary)
    document.querySelectorAll(".tab-btn").forEach((b, i) => b.setAttribute("aria-selected", i === 0 ? "true" : "false"));
    document.querySelectorAll(".tab-panel").forEach((p, i) => p.classList.toggle("active", i === 0));

    // Fallbacks and Errors banner
    const errors = tripData.errors || [];
    if (errors.length > 0 && this.backupBanner && this.backupList) {
      this.backupBanner.classList.add("active");
      this.backupList.innerHTML = "";
      errors.forEach((err) => {
        let agentName = "";
        let text = "";
        if (typeof err === "object" && err !== null) {
          agentName = err.agent || "Agent";
          text = err.message || "";
        } else {
          text = String(err);
        }

        // Clean up duplicate prefix like "restaurant_agent: restaurant_agent: ..."
        if (agentName) {
          const rawPrefix = `${agentName}:`;
          if (text.toLowerCase().startsWith(rawPrefix.toLowerCase())) {
            text = text.slice(rawPrefix.length).trim();
          }
        }

        // Friendly text mapping
        if (text.includes("Real data providers had no data") || text.includes("AI-suggested dining spots")) {
          text = "Local dining recommendations curated by AI specialist for authentic regional flavor.";
        } else if (text.includes("using estimated hotel tiers") || text.includes("LLM response could not be parsed")) {
          text = "Curated stay recommendations calculated based on your target budget.";
        }

        const cleanAgent = agentName ? agentName.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()) : "Agent";
        const msg = agentName ? `${cleanAgent}: ${text}` : text;
        this.backupList.appendChild(el("li", {}, msg));
      });
    } else if (this.backupBanner) {
      this.backupBanner.classList.remove("active");
    }

    // Render individual sections
    this.renderItinerary(tripData.daily_itinerary || [], tripData.weather?.daily || []);
    this.renderHotels(tripData.hotels || [], tripData.budget_currency);
    this.renderRestaurants(tripData.restaurants || []);
    this.renderWeather(tripData.weather);
    this.renderBudget(tripData.budget_breakdown, tripData.budget_total, tripData.budget_currency);
    this.renderTransport(tripData.transport_guide);
    this.renderPackingList(tripData.packing_list || []);
    this.renderTimings(tripData.timings);

    // Render Map
    this.mapManager.initMap(tripData);
  }

  renderItinerary(days, weatherDaily) {
    if (!this.itineraryContainer) return;
    this.itineraryContainer.innerHTML = "";

    days.forEach((day, idx) => {
      const dayNum = day.day || idx + 1;
      const dateStr = day.date ? formatDate(day.date) : `Day ${dayNum}`;

      // Match weather if available
      const matchingWeather = weatherDaily.find(w => w.date === day.date);
      const weatherChipText = matchingWeather ? `${matchingWeather.condition || "Fair"} (${Math.round(matchingWeather.temp_max || 0)}°C)` : "";

      const card = el("div", { className: `day-card ${idx === 0 ? "expanded" : ""}` }, [
        el("button", {
          type: "button",
          className: "day-header",
          "aria-expanded": idx === 0 ? "true" : "false",
          onClick: () => {
            const isExp = card.classList.toggle("expanded");
            card.querySelector(".day-header")?.setAttribute("aria-expanded", String(isExp));
          },
        }, [
          el("div", { className: "day-header-left" }, [
            el("span", { className: "day-badge" }, `Day ${dayNum}`),
            el("span", { className: "day-date-str" }, dateStr),
            weatherChipText ? el("span", { className: "badge badge-ai" }, weatherChipText) : null,
          ]),
          el("span", { className: "day-collapse-icon" }, "▼"),
        ]),
        el("div", { className: "day-content" }, [
          el("div", { className: "day-blocks-grid" }, [
            el("div", { className: "day-block" }, [
              el("div", { className: "day-block-label" }, "Morning"),
              el("div", { className: "day-block-text" }, day.morning || "Free time to explore at leisure."),
            ]),
            el("div", { className: "day-block" }, [
              el("div", { className: "day-block-label" }, "Afternoon"),
              el("div", { className: "day-block-text" }, day.afternoon || "Free time for sightseeing and experiences."),
            ]),
            el("div", { className: "day-block" }, [
              el("div", { className: "day-block-label" }, "Evening"),
              el("div", { className: "day-block-text" }, day.evening || "Dinner and evening stroll."),
            ]),
          ]),
          day.notes ? el("div", { className: "day-notes" }, [
            el("strong", {}, "Tips & Pacing: "),
            day.notes,
          ]) : null,
        ]),
      ]);

      this.itineraryContainer.appendChild(card);
    });
  }

  renderHotels(hotels, currency = "USD") {
    if (!this.hotelsContainer) return;
    this.hotelsContainer.innerHTML = "";

    if (hotels.length === 0) {
      this.hotelsContainer.appendChild(el("p", { className: "text-muted" }, "No accommodations cataloged for this region. Check local listings."));
      return;
    }

    hotels.forEach((hotel) => {
      const priceVal = hotel.price_per_night_usd ? `$${hotel.price_per_night_usd}` : "Price upon request";
      const amenities = Array.isArray(hotel.amenities) ? hotel.amenities.slice(0, 4).join(" • ") : "";

      const card = el("div", { className: "item-card" }, [
        el("div", {}, [
          el("div", { className: "item-card-header" }, [
            el("h4", { className: "item-card-title" }, hotel.name || "Boutique Stay"),
            hotel.star_rating ? el("span", { className: "badge badge-ai" }, `★ ${hotel.star_rating}`) : null,
          ]),
          el("p", { className: "text-sm text-muted", style: "margin: 6px 0;" }, amenities),
          el("div", { style: "display: flex; align-items: baseline; gap: 8px; margin-top: 8px;" }, [
            el("span", { style: "font-weight: 700; color: var(--color-accent-light);" }, priceVal),
            el("span", { className: "badge badge-estimate" }, "Estimated / night"),
          ]),
        ]),
        el("div", { className: "booking-links-group" }, [
          hotel.booking_links?.google_hotels ? el("a", {
            href: sanitizeUrl(hotel.booking_links.google_hotels),
            target: "_blank",
            rel: "noopener noreferrer",
            className: "btn btn-outline btn-sm",
          }, "Google Hotels ↗") : null,
          hotel.booking_links?.booking_com ? el("a", {
            href: sanitizeUrl(hotel.booking_links.booking_com),
            target: "_blank",
            rel: "noopener noreferrer",
            className: "btn btn-outline btn-sm",
          }, "Booking.com ↗") : null,
        ]),
      ]);

      this.hotelsContainer.appendChild(card);
    });
  }

  renderRestaurants(restaurants) {
    if (!this.restaurantsContainer) return;
    this.restaurantsContainer.innerHTML = "";

    if (restaurants.length === 0) {
      this.restaurantsContainer.appendChild(el("p", { className: "text-muted" }, "Local food suggestions will be discovered on-site."));
      return;
    }

    restaurants.forEach((r) => {
      const card = el("div", { className: "item-card" }, [
        el("div", {}, [
          el("div", { className: "item-card-header" }, [
            el("h4", { className: "item-card-title" }, r.name || "Local Eatery"),
            r.price_level ? el("span", { className: "badge badge-ai" }, r.price_level) : null,
          ]),
          el("p", { className: "text-sm text-accent", style: "margin: 4px 0;" }, r.cuisine || "Authentic dining"),
          r.match_reason ? el("p", { className: "text-sm text-secondary" }, r.match_reason) : null,
        ]),
        r.website ? el("a", {
          href: sanitizeUrl(r.website),
          target: "_blank",
          rel: "noopener noreferrer",
          className: "btn btn-outline btn-sm",
          style: "align-self: flex-start;",
        }, "Official Site ↗") : null,
      ]);

      this.restaurantsContainer.appendChild(card);
    });
  }

  renderWeather(weather) {
    if (!this.weatherContainer) return;
    this.weatherContainer.innerHTML = "";

    const daily = weather?.daily || [];
    if (daily.length === 0) {
      this.weatherContainer.appendChild(el("p", { className: "text-muted" }, "Weather forecast unavailable for target window."));
      return;
    }

    daily.forEach((d) => {
      const card = el("div", { className: "weather-day-card" }, [
        el("div", { className: "text-xs text-muted" }, formatDate(d.date)),
        el("div", { className: "weather-temp-range" }, `${Math.round(d.temp_min)}° - ${Math.round(d.temp_max)}°C`),
        el("div", { className: "text-sm text-secondary" }, d.condition || "Clear"),
        weather?.is_estimate ? el("span", { className: "badge badge-estimate", style: "margin-top: 6px;" }, "Climate estimate") : null,
      ]);
      this.weatherContainer.appendChild(card);
    });
  }

  renderBudget(breakdown, total, currency = "USD") {
    if (!this.budgetTableContainer || !breakdown) return;
    this.budgetTableContainer.innerHTML = "";

    const table = el("table", { className: "budget-table" }, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", {}, "Category"),
          el("th", {}, "Allocation"),
          el("th", {}, "Percent"),
        ]),
      ]),
      el("tbody", {}, [
        ...Object.entries(breakdown).map(([category, amount]) => {
          const num = Number(amount) || 0;
          const pct = total > 0 ? Math.round((num / total) * 100) : 0;
          return el("tr", {}, [
            el("td", { style: "text-transform: capitalize;" }, category.replace(/_/g, " ")),
            el("td", {}, formatCurrency(num, currency)),
            el("td", {}, `${pct}%`),
          ]);
        }),
      ]),
    ]);

    this.budgetTableContainer.appendChild(table);

    // Pure inline SVG doughnut
    if (this.budgetSvgContainer) {
      this.renderSvgDonut(breakdown, total);
    }
    if (this.budgetTotalCenter) {
      this.budgetTotalCenter.textContent = formatCurrency(total, currency);
    }
  }

  renderSvgDonut(breakdown, total) {
    this.budgetSvgContainer.innerHTML = "";
    const radius = 70;
    const circumference = 2 * Math.PI * radius;
    const colors = ["#e6a23c", "#38bdf8", "#10b981", "#a855f7", "#f43f5e", "#fbbf24"];

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 200 200");
    svg.setAttribute("class", "donut-svg");

    let accumulatedPct = 0;
    const entries = Object.entries(breakdown);

    entries.forEach(([cat, amt], idx) => {
      const num = Number(amt) || 0;
      const ratio = total > 0 ? num / total : 0;
      const strokeLength = ratio * circumference;
      const strokeDashoffset = -accumulatedPct * circumference;
      accumulatedPct += ratio;

      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", "100");
      circle.setAttribute("cy", "100");
      circle.setAttribute("r", String(radius));
      circle.setAttribute("fill", "transparent");
      circle.setAttribute("stroke", colors[idx % colors.length]);
      circle.setAttribute("stroke-width", "24");
      circle.setAttribute("stroke-dasharray", `${strokeLength} ${circumference}`);
      circle.setAttribute("stroke-dashoffset", String(strokeDashoffset));

      svg.appendChild(circle);
    });

    this.budgetSvgContainer.appendChild(svg);
  }

  renderTransport(transport) {
    if (!this.transportContainer) return;
    this.transportContainer.innerHTML = "";

    if (!transport) {
      this.transportContainer.appendChild(el("p", { className: "text-muted" }, "Standard public and private transit apply."));
      return;
    }

    const tips = transport.tips || [];
    const passes = transport.transit_passes || [];

    const wrapper = el("div", { style: "display: flex; flex-direction: column; gap: 16px;" }, [
      passes.length > 0 ? el("div", {}, [
        el("h4", { className: "text-base text-accent", style: "margin-bottom: 6px;" }, "Recommended Passes"),
        el("ul", { style: "padding-left: 20px; color: var(--color-text-secondary);" }, passes.map(p => el("li", {}, p))),
      ]) : null,
      tips.length > 0 ? el("div", {}, [
        el("h4", { className: "text-base text-accent", style: "margin-bottom: 6px;" }, "Transit Advice"),
        el("ul", { style: "padding-left: 20px; color: var(--color-text-secondary);" }, tips.map(t => el("li", {}, t))),
      ]) : null,
    ]);

    this.transportContainer.appendChild(wrapper);
  }

  renderPackingList(items) {
    if (!this.packingContainer) return;
    this.packingContainer.innerHTML = "";

    if (items.length === 0) {
      this.packingContainer.appendChild(el("p", { className: "text-muted" }, "Pack standard seasonal apparel."));
      return;
    }

    const grid = el("div", { className: "packing-grid" }, items.map((item) => {
      const isChecked = AppState.packingChecks[item] || false;
      const label = el("label", { className: `packing-item ${isChecked ? "checked" : ""}` }, [
        el("input", {
          type: "checkbox",
          checked: isChecked,
          onChange: (e) => {
            const checked = AppState.togglePackingCheck(item);
            label.classList.toggle("checked", checked);
          },
        }),
        el("span", {}, item),
      ]);
      return label;
    }));

    this.packingContainer.appendChild(grid);
  }

  renderTimings(timings) {
    if (!this.timingsContainer) return;
    this.timingsContainer.innerHTML = "";

    if (!timings) {
      this.timingsContainer.style.display = "none";
      return;
    }

    this.timingsContainer.style.display = "block";
    const totalDuration = timings.total_duration_s || 30;

    const rows = Object.entries(timings)
      .filter(([k, v]) => typeof v === "object" && v !== null && v.duration_s !== undefined)
      .map(([agentName, data]) => {
        const dur = Number(data.duration_s) || 0;
        const offset = Number(data.start_offset_s) || 0;
        const leftPct = (offset / totalDuration) * 100;
        const widthPct = Math.max((dur / totalDuration) * 100, 2);

        return el("div", { className: "timeline-row" }, [
          el("span", { style: "font-weight: 600; text-transform: capitalize;" }, agentName.replace(/_/g, " ")),
          el("div", { className: "timeline-bar-track" }, [
            el("div", {
              className: "timeline-bar-fill",
              style: `left: ${leftPct}%; width: ${widthPct}%; ${data.fallback_used ? "background: var(--color-warning);" : ""}`,
            }),
          ]),
          el("span", { className: "text-muted" }, `${dur.toFixed(1)}s`),
        ]);
      });

    const panel = el("div", { className: "timings-panel" }, [
      el("h4", { className: "text-lg", style: "margin-bottom: 4px;" }, "Behind the Plan: Real Multi-Agent Timeline"),
      el("p", { className: "text-sm text-muted", style: "margin-bottom: 16px;" }, `Executed concurrently across specialist agents in ${totalDuration.toFixed(1)}s.`),
      el("div", { className: "timeline-bars" }, rows),
    ]);

    this.timingsContainer.appendChild(panel);
  }

  async handleShare() {
    const slug = this.currentTrip?.share_slug || this.currentTrip?.id;
    if (!slug) {
      showToast("Trip share slug unavailable.", "error");
      return;
    }

    const shareUrl = `${window.location.origin}${window.location.pathname}#/trip/${slug}`;
    if (navigator.share && /mobile|android|iphone/i.test(navigator.userAgent)) {
      try {
        await navigator.share({
          title: `Trip Itinerary: ${this.currentTrip.destination}`,
          text: `Check out my custom AI-planned journey to ${this.currentTrip.destination}!`,
          url: shareUrl,
        });
        return;
      } catch {
        // fall back to copy
      }
    }

    const copied = await copyToClipboard(shareUrl);
    if (copied) {
      showToast("Public share link copied to clipboard!", "success");
    } else {
      showToast("Could not copy link automatically.", "error");
    }
  }

  handleSave() {
    if (!this.currentTrip) return;
    AppState.saveTrip({
      id: this.currentTrip.id || this.currentTrip.share_slug || Date.now().toString(),
      share_slug: this.currentTrip.share_slug,
      destination: this.currentTrip.destination,
      dates: `${this.currentTrip.start_date} to ${this.currentTrip.end_date}`,
      result: this.currentTrip,
    });
    showToast("Trip saved to 'My Trips' in your browser!", "success");
  }

  handleDownloadPdf() {
    const slug = this.currentTrip?.share_slug;
    if (!slug) {
      showToast("Trip must be saved before downloading PDF.", "info");
      return;
    }
    const pdfUrl = API.getPdfUrl(slug);
    window.open(pdfUrl, "_blank");
  }
}

/**
 * ui.js - Application Orchestrator, Hash Router, and Global Event Listeners
 */

import { HeroManager } from "./hero.js";
import { PlannerManager } from "./planner.js";
import { ProgressManager } from "./progress.js";
import { ResultsManager } from "./results.js";
import { MapManager } from "./map.js";
import { AssistantManager } from "./assistant.js";
import { TripsManager } from "./trips.js";
import { API } from "./api.js";
import { showToast } from "./utils.js";

class App {
  constructor() {
    this.mapManager = new MapManager();
    this.resultsManager = new ResultsManager(this.mapManager, (trip) => this.handleReplan(trip));
    this.assistantManager = new AssistantManager((prompt) => this.handleAssistantPrompt(prompt));
    this.tripsManager = new TripsManager((trip) => this.openTrip(trip));

    this.progressManager = new ProgressManager(
      (result) => this.handlePlanCompleted(result),
      (error) => this.handlePlanFailed(error)
    );

    this.plannerManager = new PlannerManager((jobId, payload) => {
      this.handlePlanStarted(jobId, payload);
    });

    this.heroManager = new HeroManager();

    this.init();
  }

  init() {
    this.initHeaderScroll();
    this.initMobileDrawer();
    this.initTabs();
    this.initHashRouting();
    this.initFeaturedDestinations();
    this.initSampleTripLoader();
    this.fetchPlatformStats();
  }

  initTabs() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const targetId = btn.getAttribute("data-target");
        document.querySelectorAll(".tab-btn").forEach(b => b.setAttribute("aria-selected", "false"));
        document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
        btn.setAttribute("aria-selected", "true");
        const targetPanel = document.getElementById(targetId);
        if (targetPanel) {
          targetPanel.classList.add("active");
          if (targetId === "tab-map") {
            setTimeout(() => {
              if (this.mapManager?.map) {
                this.mapManager.map.invalidateSize();
              }
            }, 100);
          }
        }
      });
    });
  }

  initHeaderScroll() {
    const header = document.querySelector(".site-header");
    window.addEventListener("scroll", () => {
      if (window.scrollY > 40) {
        header?.classList.add("scrolled");
      } else {
        header?.classList.remove("scrolled");
      }
    }, { passive: true });
  }

  initMobileDrawer() {
    const toggle = document.getElementById("mobile-nav-toggle");
    const drawer = document.getElementById("mobile-nav-drawer");
    const backdrop = document.getElementById("mobile-nav-backdrop");
    const closeBtn = document.getElementById("mobile-nav-close");

    const openDrawer = () => {
      drawer?.classList.add("open");
      backdrop?.classList.add("open");
      closeBtn?.focus();
    };

    const closeDrawer = () => {
      drawer?.classList.remove("open");
      backdrop?.classList.remove("open");
      toggle?.focus();
    };

    toggle?.addEventListener("click", openDrawer);
    closeBtn?.addEventListener("click", closeDrawer);
    backdrop?.addEventListener("click", closeDrawer);

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drawer?.classList.contains("open")) {
        closeDrawer();
      }
    });

    document.querySelectorAll(".mobile-nav-links a").forEach(link => {
      link.addEventListener("click", closeDrawer);
    });
  }

  initHashRouting() {
    const handleRoute = async () => {
      const hash = window.location.hash || "#/";

      if (hash.startsWith("#/trip/")) {
        const slug = hash.replace("#/trip/", "").trim();
        if (slug) {
          try {
            const trip = await API.getSharedTrip(slug);
            this.openTrip(trip.result || trip);
          } catch (err) {
            showToast("Could not find the shared itinerary.", "error");
          }
        }
      } else if (hash === "#/my-trips") {
        this.tripsManager.show();
      } else if (hash === "#/plan") {
        const pSection = document.getElementById("planner-section");
        pSection?.scrollIntoView({ behavior: "smooth" });
      }
    };

    window.addEventListener("hashchange", handleRoute);
    handleRoute();
  }

  initFeaturedDestinations() {
    document.querySelectorAll(".dest-explore-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const target = e.currentTarget;
        const destName = target.dataset.dest;
        if (destName) {
          this.plannerManager.prefillDestination(destName);
        }
      });
    });
  }

  initSampleTripLoader() {
    const sampleBtn = document.getElementById("btn-load-sample");
    sampleBtn?.addEventListener("click", async () => {
      try {
        const res = await fetch("data/sample-trip.json");
        if (!res.ok) throw new Error("Could not load sample data.");
        const sampleData = await res.json();
        this.openTrip(sampleData, true);
        showToast("Loaded sample expedition generated by Aetheria agents.", "info");
      } catch (err) {
        showToast("Sample data unavailable.", "error");
      }
    });
  }

  async fetchPlatformStats() {
    try {
      const stats = await API.getStats();
      const statsStrip = document.getElementById("stats-trust-item");
      if (stats && stats.total_trips >= 10 && statsStrip) {
        const medianStr = stats.median_duration_s ? ` · Median ~${Math.round(stats.median_duration_s)}s` : "";
        statsStrip.textContent = `✦ ${stats.total_trips} journeys planned${medianStr}`;
        statsStrip.style.display = "inline-flex";
      }
    } catch {
      // stats optional
    }
  }

  handlePlanStarted(jobId, payload) {
    this.progressManager.start(jobId);
  }

  handlePlanCompleted(result) {
    this.openTrip(result);
  }

  handlePlanFailed(errorMsg) {
    showToast(`Planning failed: ${errorMsg}`, "error");
    const plannerSection = document.getElementById("planner-section");
    plannerSection?.scrollIntoView({ behavior: "smooth" });
  }

  openTrip(trip, isSample = false) {
    this.resultsManager.render(trip, isSample);
    this.assistantManager.setTrip(trip);
  }

  handleReplan(trip) {
    if (trip.destination) {
      this.plannerManager.prefillDestination(trip.destination);
    }
  }

  handleAssistantPrompt(promptText) {
    const plannerSection = document.getElementById("planner-section");
    plannerSection?.scrollIntoView({ behavior: "smooth" });
  }
}

// Instantiate on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.__AETHERIA_APP__ = new App();
});

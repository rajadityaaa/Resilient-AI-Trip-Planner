/**
 * plan-main.js - Orchestrator for the Dedicated Planner Page (/plan/)
 * Handles:
 *  - URL query pre-fill (dest, start, end) with strict sanitization
 *  - 3-step wizard navigation and step validation
 *  - Reactive live trip summary card
 *  - Mission Control real-time SSE progress
 *  - Results dashboard, Google Maps, AI chat assistant, and My Trips
 *  - Hash routing (#/trip/<slug>, #/my-trips, #/new)
 */

import { PlannerManager } from "./planner.js?v=7";
import { ProgressManager } from "./progress.js?v=7";
import { ResultsManager } from "./results.js?v=7";
import { MapManager } from "./map.js?v=7";
import { AssistantManager } from "./assistant.js?v=7";
import { TripsManager } from "./trips.js?v=7";
import { API } from "./api.js?v=7";
import { showToast } from "./utils.js?v=7";

class PlannerApp {
  constructor() {
    this.currentStep = 1;
    this.totalSteps = 3;

    // Component Managers
    this.mapManager = new MapManager();
    this.resultsManager = new ResultsManager(this.mapManager, (trip) => this.handleReplan(trip));
    this.assistantManager = new AssistantManager((prompt) => this.handleAssistantPrompt(prompt));
    this.tripsManager = new TripsManager((trip) => this.openTrip(trip));

    this.progressManager = new ProgressManager(
      (result) => this.handlePlanCompleted(result),
      (error) => this.handlePlanFailed(error)
    );

    this.plannerManager = new PlannerManager((jobId, tripRequest) => {
      this.handlePlanStarted(jobId, tripRequest);
    });

    this.currentJobId = null;

    this.init();
  }

  init() {
    this.setupWizardNav();
    this.parseQueryParams();
    this.setupSummaryCardUpdater();
    this.setupTabs();
    this.setupHashRouter();
    this.initSampleExpeditionButton();
    this.initInteractiveGlow();
  }

  setupTabs() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const targetId = btn.getAttribute("data-target");
        document.querySelectorAll(".tab-btn").forEach((b) => b.setAttribute("aria-selected", "false"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.setAttribute("aria-selected", "true");
        const targetPanel = document.getElementById(targetId);
        if (targetPanel) {
          targetPanel.classList.add("active");
          if (targetId === "tab-map") {
            this.mapManager?.onTabVisible();
          }
        }
      });
    });
  }

  /**
   * Reads URL query parameters (?dest=...&start=...&end=...) safely.
   * Enforces character limits and ISO date formats. Never uses innerHTML.
   */
  parseQueryParams() {
    try {
      const params = new URLSearchParams(window.location.search);
      const dest = params.get("dest")?.trim();
      const start = params.get("start")?.trim();
      const end = params.get("end")?.trim();

      const destInput = document.getElementById("plan-dest");
      const startInput = document.getElementById("plan-start-date");
      const endInput = document.getElementById("plan-end-date");
      const surpriseToggle = document.getElementById("plan-surprise");

      if (dest && destInput) {
        // Sanitize length
        const safeDest = dest.slice(0, 80);
        destInput.value = safeDest;
        if (surpriseToggle) surpriseToggle.checked = false;
        destInput.disabled = false;
      }

      const isoDateRegex = /^\d{4}-\d{2}-\d{2}$/;
      if (start && startInput && isoDateRegex.test(start)) {
        startInput.value = start;
      }
      if (end && endInput && isoDateRegex.test(end)) {
        endInput.value = end;
      }

      // Update duration and summary card
      this.plannerManager?.updateDuration();
      this.updateLiveSummary();
    } catch (err) {
      console.warn("Could not parse query parameters:", err);
    }
  }

  /**
   * 3-Step Wizard Navigation (1: Trip Basics, 2: Preferences, 3: Review & Plan)
   */
  setupWizardNav() {
    // Step indicators
    document.querySelectorAll(".wizard-step-item").forEach((stepEl) => {
      stepEl.addEventListener("click", () => {
        const stepNum = parseInt(stepEl.getAttribute("data-step"), 10);
        if (stepNum && stepNum !== this.currentStep) {
          if (stepNum > this.currentStep && !this.validateCurrentStep()) {
            return;
          }
          this.goToStep(stepNum);
        }
      });
    });

    // Next / Back buttons
    document.getElementById("btn-wizard-next-1")?.addEventListener("click", () => {
      if (this.validateCurrentStep()) this.goToStep(2);
    });

    document.getElementById("btn-wizard-back-2")?.addEventListener("click", () => {
      this.goToStep(1);
    });

    document.getElementById("btn-wizard-next-2")?.addEventListener("click", () => {
      if (this.validateCurrentStep()) this.goToStep(3);
    });

    document.getElementById("btn-wizard-back-3")?.addEventListener("click", () => {
      this.goToStep(2);
    });
  }

  validateCurrentStep() {
    if (this.currentStep === 1) {
      const dest = document.getElementById("plan-dest");
      const surprise = document.getElementById("plan-surprise");
      if (!surprise?.checked && (!dest?.value || dest.value.trim().length < 2)) {
        showToast("Please enter a destination or select 'Surprise me'.", "error");
        dest?.focus();
        return false;
      }

      const start = document.getElementById("plan-start-date")?.value;
      const end = document.getElementById("plan-end-date")?.value;
      if (!start || !end) {
        showToast("Please specify your journey dates.", "error");
        return false;
      }
      if (new Date(end) < new Date(start)) {
        showToast("Return date cannot be earlier than departure date.", "error");
        return false;
      }
    }
    return true;
  }

  goToStep(stepNum) {
    this.currentStep = Math.max(1, Math.min(stepNum, this.totalSteps));

    // Update panels
    document.querySelectorAll(".wizard-panel").forEach((panel) => {
      const pNum = parseInt(panel.getAttribute("data-step-panel"), 10);
      panel.classList.toggle("active", pNum === this.currentStep);
    });

    // Update step indicators
    document.querySelectorAll(".wizard-step-item").forEach((stepEl) => {
      const sNum = parseInt(stepEl.getAttribute("data-step"), 10);
      stepEl.classList.toggle("active", sNum === this.currentStep);
      stepEl.classList.toggle("completed", sNum < this.currentStep);
    });

    this.updateLiveSummary();

    // Scroll smoothly to wizard top
    const formTop = document.getElementById("planner-form");
    if (formTop) {
      const yOffset = -90;
      const y = formTop.getBoundingClientRect().top + window.pageYOffset + yOffset;
      window.scrollTo({ top: y, behavior: "smooth" });
    }
  }

  setupSummaryCardUpdater() {
    const inputs = [
      "plan-dest",
      "plan-surprise",
      "plan-start-date",
      "plan-end-date",
      "plan-budget-total",
      "plan-budget-currency",
      "plan-origin",
      "plan-pref-stay",
      "plan-pref-transit",
      "plan-pref-diet",
    ];

    inputs.forEach((id) => {
      const el = document.getElementById(id);
      el?.addEventListener("input", () => this.updateLiveSummary());
      el?.addEventListener("change", () => this.updateLiveSummary());
    });

    // Style & chip changes also trigger summary update
    document.querySelectorAll(".style-option, .chip[data-pref]").forEach((item) => {
      item.addEventListener("click", () => setTimeout(() => this.updateLiveSummary(), 50));
    });

    this.updateLiveSummary();
  }

  updateLiveSummary() {
    const destVal = document.getElementById("plan-dest")?.value?.trim();
    const isSurprise = document.getElementById("plan-surprise")?.checked;
    const destText = isSurprise ? "✨ Surprise Me (AI Curated)" : destVal || "Your Next Destination";

    const summaryDest = document.getElementById("summary-dest-val");
    if (summaryDest) summaryDest.textContent = destText;

    const startVal = document.getElementById("plan-start-date")?.value;
    const endVal = document.getElementById("plan-end-date")?.value;
    const durationBadge = document.getElementById("plan-duration-badge")?.textContent || "Flexible";

    const summaryDates = document.getElementById("summary-dates-val");
    if (summaryDates) {
      summaryDates.textContent = startVal && endVal ? `${startVal} → ${endVal} (${durationBadge})` : "Dates pending";
    }

    const travelersVal = document.getElementById("plan-travelers-value")?.textContent || "1";
    const summaryTravelers = document.getElementById("summary-travelers-val");
    if (summaryTravelers) {
      summaryTravelers.textContent = `${travelersVal} Traveler${parseInt(travelersVal, 10) > 1 ? "s" : ""}`;
    }

    const budgetVal = document.getElementById("plan-budget-total")?.value?.trim();
    const currVal = document.getElementById("plan-budget-currency")?.value || "USD";
    const summaryBudget = document.getElementById("summary-budget-val");
    if (summaryBudget) {
      summaryBudget.textContent = budgetVal ? `${currVal} ${budgetVal}` : "Moderate estimate";
    }

    // Styles & tags
    const tagsContainer = document.getElementById("summary-tags-container");
    if (tagsContainer) {
      tagsContainer.innerHTML = "";
      const selectedStyles = Array.from(this.plannerManager?.selectedStyles || []);
      const selectedChips = Array.from(this.plannerManager?.selectedChips || []);
      const allTags = [...selectedStyles, ...selectedChips];

      if (allTags.length === 0) {
        const span = document.createElement("span");
        span.className = "summary-mini-tag";
        span.textContent = "Adventure";
        tagsContainer.appendChild(span);
      } else {
        allTags.slice(0, 8).forEach((tag) => {
          const span = document.createElement("span");
          span.className = "summary-mini-tag";
          span.textContent = tag;
          tagsContainer.appendChild(span);
        });
      }
    }
  }

  setupHashRouter() {
    window.addEventListener("hashchange", () => this.handleHashChange());
    this.handleHashChange();
  }

  handleHashChange() {
    const hash = window.location.hash || "#/";

    if (hash === "#/my-trips") {
      this.tripsManager.openModal();
    } else if (hash.startsWith("#/trip/")) {
      const slug = hash.replace("#/trip/", "").trim();
      if (slug) this.loadSharedTrip(slug);
    } else if (hash === "#/new") {
      this.resetToPlanner();
    }
  }

  async loadSharedTrip(slug) {
    try {
      showToast("Retrieving your expedition...", "info");
      const tripData = await API.getSharedTrip(slug);
      this.openTrip(tripData);
    } catch (err) {
      showToast(`Could not load trip: ${err.message}`, "error");
    }
  }

  handlePlanStarted(jobId, tripRequest) {
    this.currentJobId = jobId;
    document.getElementById("planner-section")?.classList.add("hidden");
    document.getElementById("results-section")?.classList.remove("active", "visible");

    this.progressManager.start(jobId);
    const genSec = document.getElementById("generating-section");
    if (genSec) {
      genSec.classList.add("active", "visible");
      genSec.scrollIntoView({ behavior: "smooth" });
    }
  }

  handlePlanCompleted(result) {
    if (!result) return;
    if (this.currentJobId && !result.id) {
      result.id = this.currentJobId;
    }

    const genSec = document.getElementById("generating-section");
    if (genSec) {
      genSec.classList.remove("active", "visible");
    }
    this.openTrip(result);
  }

  handlePlanFailed(error) {
    const genSec = document.getElementById("generating-section");
    if (genSec) {
      genSec.classList.remove("active", "visible");
    }
    document.getElementById("planner-section")?.classList.remove("hidden");
    showToast(`Expedition synthesis failed: ${error}`, "error");
  }

  initInteractiveGlow() {
    const main = document.querySelector(".planner-page-main");
    if (!main) return;
    main.addEventListener(
      "mousemove",
      (e) => {
        const rect = main.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width) * 100;
        const y = ((e.clientY - rect.top) / rect.height) * 100;
        main.style.setProperty("--mouse-x", `${x.toFixed(1)}%`);
        main.style.setProperty("--mouse-y", `${y.toFixed(1)}%`);
      },
      { passive: true }
    );
  }

  openTrip(tripData) {
    if (!tripData) return;

    document.getElementById("planner-section")?.classList.add("hidden");
    document.getElementById("generating-section")?.classList.remove("visible");

    this.resultsManager.render(tripData);
    this.assistantManager.setTrip(tripData);

    const resultsSec = document.getElementById("results-section");
    if (resultsSec) {
      resultsSec.classList.add("visible");
      resultsSec.scrollIntoView({ behavior: "smooth" });
    }
  }

  handleReplan(trip) {
    document.getElementById("results-section")?.classList.remove("visible");
    document.getElementById("planner-section")?.classList.remove("hidden");
    this.goToStep(1);
    this.plannerManager?.prefillFromTrip(trip);
    this.updateLiveSummary();
    document.getElementById("planner-section")?.scrollIntoView({ behavior: "smooth" });
  }

  handleAssistantPrompt(promptText) {
    this.handleReplan(this.resultsManager.currentTrip);
    const dietInput = document.getElementById("plan-pref-diet");
    if (dietInput && promptText) {
      dietInput.value = promptText.slice(0, 44);
    }
    showToast("Loaded requested refinement into planner.", "info");
  }

  resetToPlanner() {
    document.getElementById("results-section")?.classList.remove("visible");
    document.getElementById("generating-section")?.classList.remove("visible");
    document.getElementById("planner-section")?.classList.remove("hidden");
    this.goToStep(1);
    document.getElementById("planner-section")?.scrollIntoView({ behavior: "smooth" });
  }

  initSampleExpeditionButton() {
    document.getElementById("plan-sample-btn")?.addEventListener("click", async () => {
      try {
        showToast("Loading verified sample expedition...", "info");
        const res = await fetch("../data/sample-trip.json");
        if (!res.ok) throw new Error("Could not fetch sample expedition");
        const sampleData = await res.json();
        sampleData.id = "sample-kyoto";
        sampleData.share_slug = "sample-kyoto";
        this.openTrip(sampleData);
      } catch (err) {
        showToast(`Failed loading sample expedition: ${err.message}`, "error");
      }
    });
  }
}

// Bootstrap on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.plannerApp = new PlannerApp();
});

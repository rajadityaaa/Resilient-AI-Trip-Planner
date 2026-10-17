/**
 * planner.js - Interactive Trip Planner Form Validation, Chip Selection, and Submission
 */

import { API } from "./api.js";
import { AppState } from "./state.js";
import { calculateDays, showToast } from "./utils.js";
import { CONFIG } from "./config.js";

export class PlannerManager {
  constructor(onPlanStarted) {
    this.onPlanStarted = onPlanStarted;
    this.form = document.getElementById("planner-form");
    this.quickForm = document.getElementById("hero-quick-form");

    // Form inputs
    this.originInput = document.getElementById("plan-origin");
    this.destInput = document.getElementById("plan-dest");
    this.surpriseToggle = document.getElementById("plan-surprise");
    this.startDateInput = document.getElementById("plan-start-date");
    this.endDateInput = document.getElementById("plan-end-date");
    this.durationBadge = document.getElementById("plan-duration-badge");
    this.travelersValue = document.getElementById("plan-travelers-value");
    this.travelersMinus = document.getElementById("plan-travelers-minus");
    this.travelersPlus = document.getElementById("plan-travelers-plus");
    this.budgetTotalInput = document.getElementById("plan-budget-total");
    this.budgetCurrencySelect = document.getElementById("plan-budget-currency");
    this.prefCounter = document.getElementById("plan-pref-counter");
    this.customStayInput = document.getElementById("plan-pref-stay");
    this.customTransitInput = document.getElementById("plan-pref-transit");
    this.customDietInput = document.getElementById("plan-pref-diet");
    this.submitBtn = document.getElementById("plan-submit-btn");
    this.resetBtn = document.getElementById("plan-reset-btn");

    this.travelersCount = 1;
    this.selectedStyles = new Set(["adventure"]);
    this.selectedChips = new Set();

    this.init();
  }

  init() {
    if (!this.form) return;

    this.detectDefaultCurrency();
    this.initMinDates();
    this.restoreCachedValues();
    this.bindEvents();
    this.updateDuration();
    this.updatePrefCounter();
  }

  detectDefaultCurrency() {
    if (this.budgetCurrencySelect && !this.budgetCurrencySelect.value) {
      const lang = navigator.language || "";
      if (lang.includes("IN")) {
        this.budgetCurrencySelect.value = "INR";
      } else if (lang.includes("GB")) {
        this.budgetCurrencySelect.value = "GBP";
      } else if (lang.includes("DE") || lang.includes("FR") || lang.includes("IT") || lang.includes("ES")) {
        this.budgetCurrencySelect.value = "EUR";
      } else {
        this.budgetCurrencySelect.value = "USD";
      }
    }
  }

  initMinDates() {
    const today = new Date().toISOString().split("T")[0];
    if (this.startDateInput) this.startDateInput.min = today;
    if (this.endDateInput) this.endDateInput.min = today;

    // Default dates if empty: next month
    if (this.startDateInput && !this.startDateInput.value) {
      const start = new Date();
      start.setDate(start.getDate() + 14);
      const end = new Date(start);
      end.setDate(end.getDate() + 5);

      this.startDateInput.value = start.toISOString().split("T")[0];
      this.endDateInput.value = end.toISOString().split("T")[0];
    }
  }

  bindEvents() {
    // Surprise me toggle
    if (this.surpriseToggle) {
      this.surpriseToggle.addEventListener("change", () => {
        if (this.destInput) {
          this.destInput.disabled = this.surpriseToggle.checked;
          if (this.surpriseToggle.checked) {
            this.destInput.placeholder = "Agent will recommend ideal destination...";
            this.clearFieldError(this.destInput);
          } else {
            this.destInput.placeholder = "e.g., Tokyo, Japan";
          }
        }
      });
    }

    // Dates duration live update
    const updateDates = () => {
      if (this.startDateInput && this.endDateInput) {
        this.endDateInput.min = this.startDateInput.value;
        this.updateDuration();
      }
    };
    this.startDateInput?.addEventListener("change", updateDates);
    this.endDateInput?.addEventListener("change", updateDates);

    // Travelers stepper
    this.travelersMinus?.addEventListener("click", () => {
      if (this.travelersCount > 1) {
        this.travelersCount--;
        this.updateTravelers();
      }
    });

    this.travelersPlus?.addEventListener("click", () => {
      if (this.travelersCount < 20) {
        this.travelersCount++;
        this.updateTravelers();
      }
    });

    // Style options (multi-selection)
    document.querySelectorAll(".style-option").forEach((opt) => {
      opt.addEventListener("click", (e) => {
        if (e.target.tagName !== "INPUT") {
          e.preventDefault();
        }
        const checkbox = opt.querySelector("input[type='checkbox']");
        const val = checkbox ? checkbox.value : opt.dataset.style;
        if (!val) return;

        if (this.selectedStyles.has(val)) {
          if (this.selectedStyles.size > 1) {
            this.selectedStyles.delete(val);
            opt.classList.remove("selected");
            if (checkbox) checkbox.checked = false;
          } else {
            showToast("Please keep at least one travel style selected.", "info");
          }
        } else {
          this.selectedStyles.add(val);
          opt.classList.add("selected");
          if (checkbox) checkbox.checked = true;
        }
      });
    });

    // Activity chips
    document.querySelectorAll(".chip[data-pref]").forEach((chip) => {
      chip.addEventListener("click", () => {
        const val = chip.dataset.pref;
        if (this.selectedChips.has(val)) {
          this.selectedChips.delete(val);
          chip.classList.remove("selected");
        } else {
          if (this.getTotalPrefCount() >= CONFIG.MAX_PREFERENCES) {
            showToast(`Maximum ${CONFIG.MAX_PREFERENCES} preferences allowed.`, "error");
            return;
          }
          this.selectedChips.add(val);
          chip.classList.add("selected");
        }
        this.updatePrefCounter();
      });
    });

    // Custom preference inputs
    [this.customStayInput, this.customTransitInput, this.customDietInput].forEach(inp => {
      inp?.addEventListener("input", () => this.updatePrefCounter());
    });

    // Quick planner in Hero
    if (this.quickForm) {
      this.quickForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const quickDest = document.getElementById("quick-dest")?.value?.trim();
        const quickDates = document.getElementById("quick-dates")?.value?.trim();
        if (quickDest && this.destInput) {
          this.destInput.value = quickDest;
          if (this.surpriseToggle) this.surpriseToggle.checked = false;
          this.destInput.disabled = false;
        }
        const plannerSection = document.getElementById("planner-section");
        plannerSection?.scrollIntoView({ behavior: "smooth" });
        this.originInput?.focus();
      });
    }

    // Form submit
    this.form.addEventListener("submit", (e) => this.handleSubmit(e));

    // Reset button
    this.resetBtn?.addEventListener("click", () => {
      this.form.reset();
      this.selectedChips.clear();
      document.querySelectorAll(".chip[data-pref]").forEach(c => c.classList.remove("selected"));
      this.selectedStyles = new Set(["adventure"]);
      document.querySelectorAll(".style-option").forEach((opt) => {
        const val = opt.querySelector("input")?.value || opt.dataset.style;
        const isSel = val === "adventure";
        opt.classList.toggle("selected", isSel);
        const cb = opt.querySelector("input[type='checkbox']");
        if (cb) cb.checked = isSel;
      });
      this.travelersCount = 1;
      this.updateTravelers();
      this.initMinDates();
      this.updateDuration();
      this.updatePrefCounter();
      AppState.saveFormValues(null);
    });
  }

  updateTravelers() {
    if (this.travelersValue) this.travelersValue.textContent = String(this.travelersCount);
    if (this.travelersMinus) this.travelersMinus.disabled = this.travelersCount <= 1;
    if (this.travelersPlus) this.travelersPlus.disabled = this.travelersCount >= 20;
  }

  updateDuration() {
    if (!this.durationBadge || !this.startDateInput || !this.endDateInput) return;
    const days = calculateDays(this.startDateInput.value, this.endDateInput.value);
    if (days > 0) {
      this.durationBadge.textContent = `${days} day${days > 1 ? "s" : ""}`;
      this.durationBadge.style.display = "inline-flex";
    } else {
      this.durationBadge.style.display = "none";
    }
  }

  getTotalPrefCount() {
    let count = this.selectedChips.size;
    if (this.customStayInput?.value?.trim()) count++;
    if (this.customTransitInput?.value?.trim()) count++;
    if (this.customDietInput?.value?.trim()) count++;
    return count;
  }

  updatePrefCounter() {
    if (!this.prefCounter) return;
    const count = this.getTotalPrefCount();
    this.prefCounter.textContent = `${count}/${CONFIG.MAX_PREFERENCES}`;
    if (count >= CONFIG.MAX_PREFERENCES) {
      this.prefCounter.style.color = "var(--color-warning)";
    } else {
      this.prefCounter.style.color = "var(--color-accent-light)";
    }
  }

  setFieldError(inputEl, message) {
    if (!inputEl) return;
    inputEl.setAttribute("aria-invalid", "true");
    let errEl = document.getElementById(`${inputEl.id}-error`);
    if (!errEl) {
      errEl = document.createElement("div");
      errEl.id = `${inputEl.id}-error`;
      errEl.className = "form-error";
      inputEl.parentNode.appendChild(errEl);
    }
    errEl.textContent = message;
    inputEl.setAttribute("aria-describedby", errEl.id);
  }

  clearFieldError(inputEl) {
    if (!inputEl) return;
    inputEl.removeAttribute("aria-invalid");
    inputEl.removeAttribute("aria-describedby");
    const errEl = document.getElementById(`${inputEl.id}-error`);
    if (errEl) errEl.remove();
  }

  validateForm() {
    let isValid = true;

    // Origin
    if (!this.originInput?.value?.trim()) {
      this.setFieldError(this.originInput, "Starting city is required.");
      isValid = false;
    } else {
      this.clearFieldError(this.originInput);
    }

    // Destination (unless surprise me)
    if (!this.surpriseToggle?.checked && !this.destInput?.value?.trim()) {
      this.setFieldError(this.destInput, "Please specify a destination or choose 'Surprise me'.");
      isValid = false;
    } else {
      this.clearFieldError(this.destInput);
    }

    // Dates
    const startVal = this.startDateInput?.value;
    const endVal = this.endDateInput?.value;
    const today = new Date().toISOString().split("T")[0];

    if (!startVal || startVal < today) {
      this.setFieldError(this.startDateInput, "Start date must be today or later.");
      isValid = false;
    } else {
      this.clearFieldError(this.startDateInput);
    }

    if (!endVal || endVal < startVal) {
      this.setFieldError(this.endDateInput, "End date must be on or after start date.");
      isValid = false;
    } else {
      const days = calculateDays(startVal, endVal);
      if (days > 21) {
        this.setFieldError(this.endDateInput, "Trip duration cannot exceed 21 days.");
        isValid = false;
      } else {
        this.clearFieldError(this.endDateInput);
      }
    }

    // Budget
    const budgetVal = Number(this.budgetTotalInput?.value);
    if (!budgetVal || budgetVal <= 0) {
      this.setFieldError(this.budgetTotalInput, "Please enter a valid total trip budget (> 0).");
      isValid = false;
    } else {
      this.clearFieldError(this.budgetTotalInput);
    }

    return isValid;
  }

  buildPlanPayload() {
    // Style mapping:
    // User can select multiple styles (e.g. Adventure, Luxury, Family).
    // Pick the most specific trip_type for backend validation:
    // adventure > romantic > family > solo > leisure
    let mappedType = "leisure";
    const styles = Array.from(this.selectedStyles);
    if (styles.includes("adventure")) mappedType = "adventure";
    else if (styles.includes("romantic")) mappedType = "romantic";
    else if (styles.includes("family")) mappedType = "family";
    else if (styles.includes("backpacking")) mappedType = "solo";
    else mappedType = "leisure";

    // Add all chosen styles as preferences so agents tailor the itinerary to all of them
    const extraStylePrefs = styles.map(s => s);

    // Aggregate preferences (up to 10 items, max 50 chars each)
    const prefs = [...extraStylePrefs, ...Array.from(this.selectedChips)];

    if (this.customStayInput?.value?.trim()) {
      prefs.push(`stay: ${this.customStayInput.value.trim().slice(0, 44)}`);
    }
    if (this.customTransitInput?.value?.trim()) {
      prefs.push(`transport: ${this.customTransitInput.value.trim().slice(0, 39)}`);
    }
    if (this.customDietInput?.value?.trim()) {
      prefs.push(`need: ${this.customDietInput.value.trim().slice(0, 44)}`);
    }

    const sanitizedPrefs = prefs.slice(0, CONFIG.MAX_PREFERENCES).map(p => p.slice(0, CONFIG.MAX_PREFERENCE_LENGTH));

    const payload = {
      origin: this.originInput.value.trim(),
      start_date: this.startDateInput.value,
      end_date: this.endDateInput.value,
      travelers: this.travelersCount,
      budget_total: Number(this.budgetTotalInput.value),
      budget_currency: (this.budgetCurrencySelect?.value || "USD").toUpperCase(),
      trip_type: mappedType,
      preferences: sanitizedPrefs,
    };

    if (!this.surpriseToggle?.checked && this.destInput?.value?.trim()) {
      payload.destination = this.destInput.value.trim();
    }

    return payload;
  }

  async handleSubmit(e) {
    e.preventDefault();
    if (!this.validateForm()) {
      showToast("Please correct the form fields highlighted above.", "error");
      return;
    }

    const payload = this.buildPlanPayload();

    // Cache form values
    AppState.saveFormValues({
      origin: payload.origin,
      destination: payload.destination || "",
      travelers: payload.travelers,
      budget_total: payload.budget_total,
      budget_currency: payload.budget_currency,
      styles: Array.from(this.selectedStyles),
    });

    this.submitBtn.disabled = true;
    const originalText = this.submitBtn.textContent;
    this.submitBtn.textContent = "Initiating agents...";

    try {
      const response = await API.submitPlan(payload);
      if (response && response.job_id) {
        AppState.setActiveJobId(response.job_id);
        this.onPlanStarted(response.job_id, payload);
      }
    } catch (err) {
      if (err.status === 429) {
        const retrySec = err.retryAfter || 60;
        showToast(`Rate limit reached: ${err.message}. Try again in ${retrySec}s.`, "error");
        this.startCooldown(retrySec);
      } else if (err.status === 422 && err.data?.detail) {
        // Map 422 errors back to fields
        if (Array.isArray(err.data.detail)) {
          err.data.detail.forEach(d => {
            const field = d.loc?.[d.loc.length - 1];
            if (field === "origin") this.setFieldError(this.originInput, d.msg);
            else if (field === "destination") this.setFieldError(this.destInput, d.msg);
            else if (field === "start_date") this.setFieldError(this.startDateInput, d.msg);
            else if (field === "end_date") this.setFieldError(this.endDateInput, d.msg);
            else if (field === "budget_total") this.setFieldError(this.budgetTotalInput, d.msg);
          });
        }
        showToast(err.message, "error");
      } else {
        showToast(err.message || "Could not start planning job.", "error");
      }
    } finally {
      this.submitBtn.disabled = false;
      this.submitBtn.textContent = originalText;
    }
  }

  startCooldown(seconds) {
    let remaining = seconds;
    this.submitBtn.disabled = true;
    const timer = setInterval(() => {
      remaining--;
      if (remaining <= 0) {
        clearInterval(timer);
        this.submitBtn.disabled = false;
        this.submitBtn.textContent = "Plan my journey";
      } else {
        this.submitBtn.textContent = `Retry in ${remaining}s`;
      }
    }, 1000);
  }

  restoreCachedValues() {
    const cached = AppState.loadFormValues();
    if (!cached) return;
    if (this.originInput && cached.origin) this.originInput.value = cached.origin;
    if (this.destInput && cached.destination) this.destInput.value = cached.destination;
    if (this.budgetTotalInput && cached.budget_total) this.budgetTotalInput.value = cached.budget_total;
    if (this.budgetCurrencySelect && cached.budget_currency) this.budgetCurrencySelect.value = cached.budget_currency;
    if (cached.travelers) {
      this.travelersCount = cached.travelers;
      this.updateTravelers();
    }
    if (cached.styles && Array.isArray(cached.styles) && cached.styles.length > 0) {
      this.selectedStyles = new Set(cached.styles);
      document.querySelectorAll(".style-option").forEach((opt) => {
        const val = opt.querySelector("input")?.value || opt.dataset.style;
        const isSel = this.selectedStyles.has(val);
        opt.classList.toggle("selected", isSel);
        const cb = opt.querySelector("input[type='checkbox']");
        if (cb) cb.checked = isSel;
      });
    }
  }

  prefillDestination(destinationName) {
    if (this.destInput) {
      this.destInput.value = destinationName;
      if (this.surpriseToggle) this.surpriseToggle.checked = false;
      this.destInput.disabled = false;
    }
    const plannerSection = document.getElementById("planner-section");
    plannerSection?.scrollIntoView({ behavior: "smooth" });
    this.originInput?.focus();
  }
}

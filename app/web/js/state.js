/**
 * state.js - Reactive Application State & Safe Local Storage Store
 */

import { CONFIG } from "./config.js";

const STORAGE_KEYS = {
  SAVED_TRIPS: "aetheria_saved_trips",
  FORM_VALUES: "aetheria_form_values",
  PACKING_CHECKS: "aetheria_packing_checks",
  JOB_ID: "aetheria_active_job_id",
};

export const AppState = {
  currentTrip: null,
  activeJobId: null,
  isGenerating: false,
  savedTrips: [],
  packingChecks: {},

  init() {
    this.savedTrips = this.loadSavedTrips();
    this.packingChecks = this.loadPackingChecks();
  },

  /* ── Safe LocalStorage Wrappers ── */
  loadSavedTrips() {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.SAVED_TRIPS);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  },

  saveTrip(trip) {
    if (!trip || !trip.id) return;
    try {
      const existing = this.loadSavedTrips().filter(t => t.id !== trip.id);
      const entry = {
        id: trip.id,
        share_slug: trip.share_slug || trip.id,
        destination: trip.destination || trip.result?.destination || "Unknown Destination",
        dates: trip.dates || `${trip.result?.start_date || ""} to ${trip.result?.end_date || ""}`.trim(),
        savedAt: new Date().toISOString(),
      };
      existing.unshift(entry);
      const capped = existing.slice(0, CONFIG.MAX_SAVED_TRIPS);
      localStorage.setItem(STORAGE_KEYS.SAVED_TRIPS, JSON.stringify(capped));
      this.savedTrips = capped;
    } catch {
      // storage unavailable or full
    }
  },

  removeSavedTrip(tripId) {
    try {
      const existing = this.loadSavedTrips().filter(t => t.id !== tripId);
      localStorage.setItem(STORAGE_KEYS.SAVED_TRIPS, JSON.stringify(existing));
      this.savedTrips = existing;
    } catch {
      // storage unavailable
    }
  },

  clearSavedTrips() {
    try {
      localStorage.removeItem(STORAGE_KEYS.SAVED_TRIPS);
      this.savedTrips = [];
    } catch {
      // storage unavailable
    }
  },

  /* ── Packing List Checkmarks ── */
  loadPackingChecks() {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.PACKING_CHECKS);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  },

  togglePackingCheck(itemText) {
    try {
      this.packingChecks[itemText] = !this.packingChecks[itemText];
      localStorage.setItem(STORAGE_KEYS.PACKING_CHECKS, JSON.stringify(this.packingChecks));
    } catch {
      // storage unavailable
    }
    return this.packingChecks[itemText];
  },

  /* ── Form Cache ── */
  saveFormValues(values) {
    try {
      localStorage.setItem(STORAGE_KEYS.FORM_VALUES, JSON.stringify(values));
    } catch {
      // storage unavailable
    }
  },

  loadFormValues() {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.FORM_VALUES);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  },

  /* ── Active Job ID (Session) ── */
  setActiveJobId(jobId) {
    this.activeJobId = jobId;
    try {
      if (jobId) {
        sessionStorage.setItem(STORAGE_KEYS.JOB_ID, jobId);
      } else {
        sessionStorage.removeItem(STORAGE_KEYS.JOB_ID);
      }
    } catch {
      // storage unavailable
    }
  },

  getActiveJobId() {
    if (this.activeJobId) return this.activeJobId;
    try {
      return sessionStorage.getItem(STORAGE_KEYS.JOB_ID);
    } catch {
      return null;
    }
  },
};

AppState.init();

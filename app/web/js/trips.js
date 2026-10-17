/**
 * trips.js - My Trips Storage, Deletion, and Loading
 */

import { AppState } from "./state.js";
import { API } from "./api.js";
import { el, formatDate, showToast, copyToClipboard } from "./utils.js";

export class TripsManager {
  constructor(onOpenTrip) {
    this.onOpenTrip = onOpenTrip;
    this.section = document.getElementById("my-trips-section");
    this.modal = document.getElementById("my-trips-modal") || document.getElementById("my-trips-view");
    this.backdrop = document.getElementById("my-trips-backdrop");
    this.closeBtn = document.getElementById("my-trips-close");
    this.grid = document.getElementById("saved-trips-grid");
    this.emptyState = document.getElementById("empty-trips-state");
    this.btnClearAll = document.getElementById("btn-clear-all-trips");

    this.init();
  }

  init() {
    this.btnClearAll?.addEventListener("click", () => {
      if (confirm("Are you sure you want to remove all saved trips from this device?")) {
        AppState.clearSavedTrips();
        this.render();
        showToast("All saved trips cleared.", "info");
      }
    });

    this.closeBtn?.addEventListener("click", () => this.closeModal());
    this.backdrop?.addEventListener("click", () => this.closeModal());
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.isModalOpen()) {
        this.closeModal();
      }
    });
  }

  isModalOpen() {
    return this.modal?.classList.contains("active") || false;
  }

  openModal() {
    this.render();
    if (this.modal) {
      this.modal.classList.add("active");
      this.backdrop?.classList.add("active");
      document.body.style.overflow = "hidden";
    } else if (this.section) {
      this.show();
    }
  }

  closeModal() {
    this.modal?.classList.remove("active");
    this.backdrop?.classList.remove("active");
    document.body.style.overflow = "";
    if (window.location.hash === "#/my-trips") {
      history.replaceState(null, "", window.location.pathname);
    }
  }

  show() {
    if (this.modal) {
      this.openModal();
      return;
    }
    if (!this.section) return;
    this.section.classList.add("active");
    this.section.scrollIntoView({ behavior: "smooth" });
    this.render();
  }

  hide() {
    this.closeModal();
    this.section?.classList.remove("active");
  }

  render() {
    if (!this.grid) return;
    this.grid.innerHTML = "";

    const trips = AppState.loadSavedTrips();
    if (trips.length === 0) {
      if (this.emptyState) this.emptyState.style.display = "block";
      if (this.btnClearAll) this.btnClearAll.style.display = "none";
      return;
    }

    if (this.emptyState) this.emptyState.style.display = "none";
    if (this.btnClearAll) this.btnClearAll.style.display = "inline-flex";

    trips.forEach((t) => {
      const card = el("div", { className: "saved-trip-card" }, [
        el("div", {}, [
          el("h3", { className: "saved-trip-dest" }, t.destination),
          el("div", { className: "saved-trip-dates" }, t.dates),
          el("div", { className: "text-xs text-muted", style: "margin-top: 4px;" }, `Saved ${formatDate(t.savedAt?.split("T")[0])}`),
        ]),
        el("div", { className: "saved-trip-actions" }, [
          el("button", {
            type: "button",
            className: "btn btn-primary btn-sm",
            onClick: async () => {
              try {
                const fullTrip = await API.getTrip(t.id);
                this.hide();
                this.onOpenTrip(fullTrip.result || fullTrip);
              } catch (err) {
                // If private ID fails, try public share slug
                try {
                  const shared = await API.getSharedTrip(t.share_slug);
                  this.hide();
                  this.onOpenTrip(shared.result || shared);
                } catch {
                  showToast("Could not retrieve saved trip.", "error");
                }
              }
            },
          }, "View Journey"),
          el("button", {
            type: "button",
            className: "btn btn-outline btn-sm",
            onClick: async () => {
              const url = `${window.location.origin}${window.location.pathname}#/trip/${t.share_slug}`;
              const copied = await copyToClipboard(url);
              if (copied) showToast("Share link copied!", "success");
            },
          }, "Share"),
          el("button", {
            type: "button",
            className: "btn btn-ghost btn-sm text-error",
            onClick: async () => {
              if (confirm(`Remove ${t.destination} from your saved trips?`)) {
                try {
                  await API.deleteTrip(t.id);
                } catch {
                  // even if backend delete fails, remove locally
                }
                AppState.removeSavedTrip(t.id);
                this.render();
                showToast("Trip removed.", "info");
              }
            },
          }, "Delete"),
        ]),
      ]);

      this.grid.appendChild(card);
    });
  }
}

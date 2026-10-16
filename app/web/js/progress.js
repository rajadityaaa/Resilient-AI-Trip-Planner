/**
 * progress.js - Real-Time Multi-Agent Pipeline Progress Tracker
 */

import { STAGES } from "./config.js";
import { el } from "./utils.js";
import { API } from "./api.js";

export class ProgressManager {
  constructor(onPlanCompleted, onPlanFailed) {
    this.onPlanCompleted = onPlanCompleted;
    this.onPlanFailed = onPlanFailed;

    this.section = document.getElementById("generating-section");
    this.stagesList = document.getElementById("stages-list");
    this.progressBar = document.getElementById("progress-fill");
    this.progressPercent = document.getElementById("progress-percent");
    this.elapsedTimer = document.getElementById("elapsed-timer");
    this.coldStartNotice = document.getElementById("cold-start-notice");

    this.timerInterval = null;
    this.startTime = null;
    this.activeSubscription = null;

    this.init();
  }

  init() {
    this.renderInitialStages();
  }

  renderInitialStages() {
    if (!this.stagesList) return;
    this.stagesList.innerHTML = "";

    STAGES.forEach((stage) => {
      const item = el("div", {
        className: "stage-item",
        id: `stage-${stage.key}`,
        "data-status": "pending",
      }, [
        el("div", { className: "stage-left" }, [
          el("div", { className: "stage-status-icon" }, "○"),
          el("span", { className: "stage-name" }, stage.label),
        ]),
        el("span", { className: "stage-detail", id: `stage-detail-${stage.key}` }, "Queued"),
      ]);
      this.stagesList.appendChild(item);
    });
  }

  start(jobId) {
    if (!this.section) return;
    this.section.classList.add("active");
    this.section.scrollIntoView({ behavior: "smooth" });

    this.renderInitialStages();
    this.startTime = Date.now();
    this.startElapsedTimer();

    // Check cold-start / wake up probe
    this.checkColdStart();

    // Subscribe to SSE with polling fallback
    this.activeSubscription = API.subscribePlanEvents(jobId, {
      onProgress: (data) => this.handleProgress(data),
      onDone: (result) => {
        this.finishSuccess(result);
      },
      onError: (errMsg) => {
        this.finishError(errMsg);
      },
    });
  }

  async checkColdStart() {
    const isHealthy = await API.checkHealth(3000);
    if (!isHealthy && this.coldStartNotice) {
      this.coldStartNotice.classList.add("active");
    }
  }

  startElapsedTimer() {
    if (this.timerInterval) clearInterval(this.timerInterval);
    this.timerInterval = setInterval(() => {
      if (!this.startTime) return;
      const elapsedSec = Math.floor((Date.now() - this.startTime) / 1000);
      if (this.elapsedTimer) {
        this.elapsedTimer.textContent = `${elapsedSec}s`;
      }
    }, 1000);
  }

  stopElapsedTimer() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  }

  handleProgress(payload) {
    if (this.coldStartNotice) {
      this.coldStartNotice.classList.remove("active");
    }

    const stages = payload.stages || {};
    let completedCount = 0;

    for (const stage of STAGES) {
      const stageData = stages[stage.key];
      const itemEl = document.getElementById(`stage-${stage.key}`);
      const detailEl = document.getElementById(`stage-detail-${stage.key}`);
      const iconEl = itemEl?.querySelector(".stage-status-icon");

      if (!stageData || !itemEl) continue;

      const status = stageData.status || "pending";
      const detail = stageData.detail || "";

      itemEl.dataset.status = status;

      if (detailEl) {
        detailEl.textContent = detail || (status === "done" ? "Completed" : status);
      }

      if (iconEl) {
        if (status === "running") {
          iconEl.textContent = "⟳";
        } else if (status === "done") {
          iconEl.textContent = "✓";
          completedCount++;
        } else if (status === "warn") {
          iconEl.textContent = "!";
          completedCount++;
        } else if (status === "failed") {
          iconEl.textContent = "✕";
        } else {
          iconEl.textContent = "○";
        }
      }
    }

    const total = STAGES.length;
    const pct = Math.round((completedCount / total) * 100);
    if (this.progressBar) this.progressBar.style.width = `${pct}%`;
    if (this.progressPercent) this.progressPercent.textContent = `${pct}%`;
  }

  finishSuccess(result) {
    this.stopElapsedTimer();
    if (this.progressBar) this.progressBar.style.width = "100%";
    if (this.progressPercent) this.progressPercent.textContent = "100%";

    setTimeout(() => {
      this.section.classList.remove("active");
      this.onPlanCompleted(result);
    }, 600);
  }

  finishError(errMsg) {
    this.stopElapsedTimer();
    this.section.classList.remove("active");
    this.onPlanFailed(errMsg);
  }

  stop() {
    if (this.activeSubscription) {
      this.activeSubscription.stop();
      this.activeSubscription = null;
    }
    this.stopElapsedTimer();
    this.section?.classList.remove("active");
  }
}

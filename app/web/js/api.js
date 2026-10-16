/**
 * api.js - Backend API Client, SSE Stream Consumer, and Polling Fallback
 */

import { CONFIG } from "./config.js";

class ApiError extends Error {
  constructor(message, status, data = null, retryAfter = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
    this.retryAfter = retryAfter;
  }
}

async function request(path, options = {}) {
  const url = `${CONFIG.API_BASE}${path}`;
  const headers = {
    "Accept": "application/json",
    ...options.headers,
  };

  if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err) {
    throw new ApiError("Network error: Could not connect to travel planner service.", 0);
  }

  const retryAfter = response.headers.get("Retry-After");

  if (!response.ok) {
    let errData = null;
    try {
      errData = await response.json();
    } catch {
      // not JSON
    }

    let message = errData?.detail || errData?.error || `HTTP ${response.status} Error`;
    if (Array.isArray(message)) {
      message = message.map(m => m.msg || JSON.stringify(m)).join(", ");
    }

    throw new ApiError(message, response.status, errData, retryAfter);
  }

  if (response.status === 204) return null;
  return response.json();
}

export const API = {
  /** Check server health (probe for cold starts) */
  async checkHealth(timeoutMs = 4000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(`${CONFIG.API_BASE}/health`, { signal: controller.signal });
      clearTimeout(timeout);
      return res.ok;
    } catch {
      clearTimeout(timeout);
      return false;
    }
  },

  /** Submit new trip planning job */
  async submitPlan(payload) {
    return request("/api/plan", {
      method: "POST",
      body: payload,
    });
  },

  /** Poll job status */
  async getPlanStatus(jobId) {
    return request(`/api/plan/${encodeURIComponent(jobId)}`);
  },

  /** Get full trip by private ID */
  async getTrip(tripId) {
    return request(`/api/trips/${encodeURIComponent(tripId)}`);
  },

  /** Get public read-only trip by share slug */
  async getSharedTrip(slug) {
    return request(`/api/share/${encodeURIComponent(slug)}`);
  },

  /** Delete trip by ID */
  async deleteTrip(tripId) {
    return request(`/api/trips/${encodeURIComponent(tripId)}`, {
      method: "DELETE",
    });
  },

  /** Get platform aggregate stats */
  async getStats() {
    return request("/api/stats");
  },

  /** Send message to interactive assistant */
  async sendChatMessage(tripIdOrSlug, message) {
    return request("/api/chat", {
      method: "POST",
      body: {
        trip_id_or_slug: tripIdOrSlug,
        message: message,
      },
    });
  },

  /** Return URL for direct PDF download */
  getPdfUrl(slug) {
    return `${CONFIG.API_BASE}/api/share/${encodeURIComponent(slug)}/pdf`;
  },

  /**
   * Listen to real-time planning progress via Server-Sent Events (SSE)
   * with automatic, graceful fallback to polling every 2s if SSE fails or disconnects.
   */
  subscribePlanEvents(jobId, { onProgress, onDone, onError }) {
    let isTerminated = false;
    let eventSource = null;
    let pollTimer = null;

    const stop = () => {
      isTerminated = true;
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    // Polling fallback
    const startPolling = () => {
      if (isTerminated || pollTimer) return;
      pollTimer = setInterval(async () => {
        if (isTerminated) return;
        try {
          const status = await API.getPlanStatus(jobId);
          if (status.status === "done") {
            stop();
            onDone(status.result);
          } else if (status.status === "failed") {
            stop();
            onError(status.error || "Trip planning failed.");
          }
        } catch (err) {
          if (err.status === 404) {
            stop();
            onError("Planning job not found.");
          }
        }
      }, CONFIG.POLL_INTERVAL_MS);
    };

    // Try EventSource first
    try {
      const sseUrl = `${CONFIG.API_BASE}/api/plan/${encodeURIComponent(jobId)}/events`;
      eventSource = new EventSource(sseUrl);

      eventSource.addEventListener("progress", (e) => {
        if (isTerminated) return;
        try {
          const data = JSON.parse(e.data);
          onProgress(data);
        } catch {
          // ignore parse errors
        }
      });

      eventSource.addEventListener("done", (e) => {
        if (isTerminated) return;
        stop();
        try {
          const data = JSON.parse(e.data);
          onDone(data.result);
        } catch (err) {
          onError("Could not parse trip results.");
        }
      });

      eventSource.addEventListener("error", (e) => {
        if (isTerminated) return;
        // Check if server sent a formal terminal error event
        if (e.data) {
          try {
            const data = JSON.parse(e.data);
            stop();
            onError(data.error || "Planning job failed.");
            return;
          } catch {
            // standard disconnect
          }
        }
        // Fall back to polling immediately if SSE disconnects
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        startPolling();
      });
    } catch {
      // EventSource unavailable; proceed with polling
      startPolling();
    }

    return { stop };
  },
};

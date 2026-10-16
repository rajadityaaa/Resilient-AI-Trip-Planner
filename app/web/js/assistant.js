/**
 * assistant.js - Interactive AI Travel Assistant & Trip Refinement
 */

import { API } from "./api.js";
import { el, showToast } from "./utils.js";

export class AssistantManager {
  constructor(onReplanWithPrompt) {
    this.onReplanWithPrompt = onReplanWithPrompt;
    this.container = document.getElementById("assistant-messages");
    this.form = document.getElementById("assistant-form");
    this.input = document.getElementById("assistant-input");
    this.suggestionsContainer = document.getElementById("assistant-suggestions");
    this.currentTripIdOrSlug = null;

    this.init();
  }

  init() {
    this.form?.addEventListener("submit", (e) => this.handleSubmit(e));
    this.renderSuggestions([
      "Make it cheaper with budget alternatives",
      "Prioritize authentic street food experiences",
      "Add a scenic day trip outside the center",
      "Recommend relaxing evening activities",
    ]);
  }

  setTrip(trip) {
    this.currentTripIdOrSlug = trip?.share_slug || trip?.id;
    if (this.container) {
      this.container.innerHTML = "";
      this.appendMessage("assistant", `Hello! I'm your travel assistant for your trip to ${trip?.destination || "your destination"}. Ask me for adjustments, pacing questions, or dining recommendations.`);
    }
  }

  renderSuggestions(suggestions) {
    if (!this.suggestionsContainer) return;
    this.suggestionsContainer.innerHTML = "";

    suggestions.forEach((text) => {
      const btn = el("button", {
        type: "button",
        className: "chip",
        onClick: () => {
          if (this.input) {
            this.input.value = text;
            this.input.focus();
          }
        },
      }, text);
      this.suggestionsContainer.appendChild(btn);
    });
  }

  appendMessage(role, text) {
    if (!this.container) return;
    const bubble = el("div", {
      className: `chat-bubble chat-bubble-${role}`,
    }, text);
    this.container.appendChild(bubble);
    this.container.scrollTop = this.container.scrollHeight;
  }

  async handleSubmit(e) {
    e.preventDefault();
    const query = this.input?.value?.trim();
    if (!query) return;

    if (!this.currentTripIdOrSlug) {
      showToast("Please plan or open a trip first.", "info");
      return;
    }

    this.appendMessage("user", query);
    this.input.value = "";

    const submitBtn = this.form.querySelector("button[type='submit']");
    if (submitBtn) submitBtn.disabled = true;

    const thinkingBubble = el("div", { className: "chat-bubble chat-bubble-assistant text-muted" }, "Consulting itinerary context...");
    this.container.appendChild(thinkingBubble);
    this.container.scrollTop = this.container.scrollHeight;

    try {
      const res = await API.sendChatMessage(this.currentTripIdOrSlug, query);
      thinkingBubble.remove();
      this.appendMessage("assistant", res.reply || "I am ready to help refine your itinerary.");
    } catch (err) {
      thinkingBubble.remove();
      this.appendMessage("assistant", `Could not consult the assistant: ${err.message}`);
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }
}

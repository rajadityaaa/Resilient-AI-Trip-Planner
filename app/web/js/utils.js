/**
 * utils.js - DOM Helpers, XSS Prevention, Toast Notifications, and Formatters
 */

/**
 * Create a DOM element safely without innerHTML.
 * Prevents XSS when rendering API or LLM generated strings.
 */
export function el(tag, attrs = {}, children = []) {
  const element = document.createElement(tag);

  for (const [key, val] of Object.entries(attrs)) {
    if (val === undefined || val === null) continue;
    if (key.startsWith("on") && typeof val === "function") {
      element.addEventListener(key.slice(2).toLowerCase(), val);
    } else if (key === "className") {
      element.className = val;
    } else if (key === "dataset" && typeof val === "object") {
      Object.assign(element.dataset, val);
    } else {
      element.setAttribute(key, val);
    }
  }

  const childList = Array.isArray(children) ? children : [children];
  for (const child of childList) {
    if (child === undefined || child === null) continue;
    if (typeof child === "string" || typeof child === "number") {
      element.appendChild(document.createTextNode(String(child)));
    } else if (child instanceof Node) {
      element.appendChild(child);
    }
  }

  return element;
}

/**
 * Sanitize external URLs. Only allow http: and https: protocols.
 */
export function sanitizeUrl(url) {
  if (!url || typeof url !== "string") return "#";
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch {
    // invalid URL
  }
  return "#";
}

/**
 * Format currency amount with currency symbol or code.
 */
export function formatCurrency(amount, currency = "USD") {
  const num = Number(amount) || 0;
  try {
    return new Intl.NumberFormat(navigator.language || "en-US", {
      style: "currency",
      currency: currency.toUpperCase(),
      maximumFractionDigits: 0,
    }).format(num);
  } catch {
    return `${currency.toUpperCase()} ${num.toLocaleString()}`;
  }
}

/**
 * Format ISO date string into readable format (e.g., "Oct 24, 2026").
 */
export function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString(navigator.language || "en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

/**
 * Calculate difference in days between two YYYY-MM-DD dates inclusive.
 */
export function calculateDays(startStr, endStr) {
  if (!startStr || !endStr) return 0;
  const s = new Date(startStr + "T00:00:00");
  const e = new Date(endStr + "T00:00:00");
  const diffTime = e.getTime() - s.getTime();
  if (diffTime < 0) return 0;
  return Math.round(diffTime / (1000 * 60 * 60 * 24)) + 1;
}

/**
 * Show accessible toast notification.
 */
export function showToast(message, type = "info", durationMs = 4000) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = el("div", { id: "toast-container", className: "toast-container", "aria-live": "polite" });
    document.body.appendChild(container);
  }

  const toast = el("div", {
    className: `toast toast-${type}`,
    role: "status",
  }, [
    el("span", { className: "toast-msg" }, message),
  ]);

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 200ms ease";
    setTimeout(() => toast.remove(), 200);
  }, durationMs);
}

/**
 * Copy text to clipboard with fallback.
 */
export async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fallback
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.left = "-999999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    document.execCommand("copy");
    textArea.remove();
    return true;
  } catch {
    textArea.remove();
    return false;
  }
}

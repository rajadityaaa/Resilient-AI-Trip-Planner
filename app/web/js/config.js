/**
 * config.js - Application Configuration & Pipeline Stage Definitions
 */

export const CONFIG = {
  API_BASE: (typeof window !== "undefined" && window.__TRAVEL_CONFIG__?.API_BASE) || "",
  POLL_INTERVAL_MS: 2000,
  HEARTBEAT_TIMEOUT_MS: 20000,
  MAX_PREFERENCES: 10,
  MAX_PREFERENCE_LENGTH: 50,
  MAX_SAVED_TRIPS: 20,
};

export const STAGES = [
  { key: "destination", label: "Destination Research", icon: "compass" },
  { key: "weather", label: "Weather Forecast", icon: "cloud-sun" },
  { key: "attractions", label: "Attractions & Sights", icon: "landmark" },
  { key: "restaurants", label: "Dining & Culinary", icon: "utensils" },
  { key: "hotels", label: "Accommodations", icon: "hotel" },
  { key: "budget_breakdown", label: "Budget Allocation", icon: "wallet" },
  { key: "transport_guide", label: "Local Transport", icon: "bus" },
  { key: "packing_list", label: "Packing Essentials", icon: "briefcase" },
  { key: "currency_info", label: "Currency & Tips", icon: "coins" },
  { key: "summary", label: "Day-by-Day Itinerary", icon: "calendar" },
];

export const HERO_SCENES = [
  {
    name: "Santorini, Greece",
    slug: "santorini",
    imgBase: "assets/img/hero-1-santorini",
    desc: "Iconic whitewashed cliffs and azure Aegean waters.",
  },
  {
    name: "Swiss Alps, Switzerland",
    slug: "swiss-alps",
    imgBase: "assets/img/hero-2-swiss-alps",
    desc: "Glacial summits, alpine trains, and crystalline air.",
  },
  {
    name: "Kyoto, Japan",
    slug: "kyoto",
    imgBase: "assets/img/hero-3-kyoto",
    desc: "Ancient wooden shrines and serene bamboo groves.",
  },
  {
    name: "Bali, Indonesia",
    slug: "bali",
    imgBase: "assets/img/hero-4-bali",
    desc: "Cascading emerald rice terraces and spiritual tranquility.",
  },
  {
    name: "Maldives",
    slug: "maldives",
    imgBase: "assets/img/hero-5-maldives",
    desc: "Overwater sanctuaries surrounded by pure turquoise lagoons.",
  },
  {
    name: "Alpine Mountain Pass",
    slug: "mountain-road",
    imgBase: "assets/img/hero-6-mountain-road",
    desc: "Dramatic hairpin curves through untamed peaks.",
  },
  {
    name: "Florence, Italy",
    slug: "florence",
    imgBase: "assets/img/hero-7-florence",
    desc: "Renaissance grandeur glowing under golden Tuscan sunsets.",
  },
];

/**
 * landing.js - Cinematic Landing Page Orchestrator (No Video, Pure CSS/SVG Motion)
 * Features:
 *  - 6-scene full-viewport photo slideshow with Ken Burns zoom and scene atmospheres
 *  - Day / Night ambient lighting toggle (session-persisted)
 *  - Foreground parallax depth on desktop pointer devices
 *  - Adaptive performance tiers (reduced-motion, saveData, lite hardware)
 *  - Sticky split sample itinerary & lazy-loaded Leaflet map
 *  - Looping Agent Pipeline Simulation (Mission Control preview) with pause control
 *  - Interactive Destination Mood Explorer
 *  - Sample budget & packing list interactive previews
 *  - Sticky "Plan my trip" floating CTA
 *  - Backward compatibility redirect for old /#/trip/<slug> hash links
 */

// 1. Backward Compatibility Hash Redirect
if (window.location.hash && (window.location.hash.startsWith("#/trip/") || window.location.hash === "#/my-trips")) {
  window.location.replace("/plan/" + window.location.hash);
}

class LandingOrchestrator {
  constructor() {
    this.currentSceneIdx = 0;
    this.scenes = [
      { id: "santorini", name: "Santorini, Greece", color: "#1e3a8a" },
      { id: "alps", name: "Swiss Alps, Switzerland", color: "#0f172a" },
      { id: "kyoto", name: "Kyoto, Japan", color: "#831843" },
      { id: "bali", name: "Bali, Indonesia", color: "#064e3b" },
      { id: "maldives", name: "Baa Atoll, Maldives", color: "#0e7490" },
      { id: "florence", name: "Florence, Italy", color: "#7c2d12" },
    ];

    this.slideshowInterval = null;
    this.isSlideshowPaused = false;
    this.isHeroInView = true;
    this.sampleMap = null;
    this.sampleMapLoaded = false;
    this.simStep = 0;
    this.simInterval = null;
    this.isSimPaused = false;

    this.init();
  }

  init() {
    this.detectPerformanceTier();
    this.setupSlideshow();
    this.setupAtmosphereControls();
    this.setupDayNightToggle();
    this.setupParallaxDepth();
    this.setupStickyPlanFab();
    this.setupLazySplitMap();
    this.setupAgentSimulation();
    this.setupMoodExplorer();
    this.setupInteractivePreviews();
    this.fetchRealStats();
  }

  detectPerformanceTier() {
    // Check reduced motion
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) {
      document.body.classList.add("mode-reduced-motion");
    }

    // Check Save-Data header or slow network
    const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (conn && (conn.saveData || conn.effectiveType === "2g" || conn.effectiveType === "slow-2g")) {
      document.body.classList.add("mode-save-data");
    }

    // Check hardware tier
    const cores = navigator.hardwareConcurrency || 4;
    const memory = navigator.deviceMemory || 4;
    if (cores <= 4 || memory <= 4) {
      document.body.classList.add("mode-lite");
    }
  }

  setupSlideshow() {
    const slides = document.querySelectorAll(".hero-slide");
    const dots = document.querySelectorAll(".hero-dot-btn");
    const label = document.getElementById("hero-now-showing-text");

    const goToScene = (idx) => {
      this.currentSceneIdx = (idx + this.scenes.length) % this.scenes.length;

      // Update slides
      slides.forEach((s, i) => s.classList.toggle("active", i === this.currentSceneIdx));
      dots.forEach((d, i) => d.classList.toggle("active", i === this.currentSceneIdx));

      // Update label
      if (label) {
        label.textContent = `Now showing: ${this.scenes[this.currentSceneIdx].name}`;
      }

      // Activate scene atmosphere
      document.querySelectorAll(".scene-atmosphere").forEach((atm) => {
        const isMatch = atm.getAttribute("data-scene") === this.scenes[this.currentSceneIdx].id;
        atm.classList.toggle("active", isMatch);
      });
    };

    dots.forEach((dot, idx) => {
      dot.addEventListener("click", () => {
        goToScene(idx);
        this.resetSlideshowTimer();
      });
    });

    this.startSlideshowTimer = () => {
      if (this.slideshowInterval) clearInterval(this.slideshowInterval);
      this.slideshowInterval = setInterval(() => {
        if (!this.isSlideshowPaused && this.isHeroInView) {
          goToScene(this.currentSceneIdx + 1);
        }
      }, 8000);
    };

    this.resetSlideshowTimer = () => {
      this.startSlideshowTimer();
    };

    this.startSlideshowTimer();

    // IntersectionObserver to pause when hero is off-screen
    const heroSection = document.getElementById("hero-section");
    if (heroSection && "IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        this.isHeroInView = entries[0].isIntersecting;
      }, { threshold: 0.1 });
      observer.observe(heroSection);
    }

    // VisibilityChange to pause when tab is in background
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.isHeroInView = false;
      } else {
        const rect = heroSection?.getBoundingClientRect();
        this.isHeroInView = !!(rect && rect.bottom > 0);
      }
    });

    // Populate particles for Swiss Alps & Kyoto
    this.generateParticles();
  }

  generateParticles() {
    // Snowflakes for Alps (max 28 elements)
    const alpsAtm = document.querySelector(".scene-atmosphere[data-scene='alps']");
    if (alpsAtm) {
      for (let i = 0; i < 26; i++) {
        const flake = document.createElement("div");
        flake.className = "snow-flake";
        const size = Math.random() * 4 + 2;
        flake.style.width = `${size}px`;
        flake.style.height = `${size}px`;
        flake.style.left = `${Math.random() * 100}%`;
        flake.style.animationDuration = `${Math.random() * 6 + 5}s`;
        flake.style.animationDelay = `${Math.random() * 5}s`;
        alpsAtm.appendChild(flake);
      }
    }

    // Sakura petals for Kyoto (max 20 elements)
    const kyotoAtm = document.querySelector(".scene-atmosphere[data-scene='kyoto']");
    if (kyotoAtm) {
      for (let i = 0; i < 18; i++) {
        const petal = document.createElement("div");
        petal.className = "sakura-petal";
        petal.style.left = `${Math.random() * 100}%`;
        petal.style.animationDuration = `${Math.random() * 7 + 6}s`;
        petal.style.animationDelay = `${Math.random() * 6}s`;
        kyotoAtm.appendChild(petal);
      }
    }

    // Fireflies for Bali (max 15 elements)
    const baliAtm = document.querySelector(".scene-atmosphere[data-scene='bali']");
    if (baliAtm) {
      for (let i = 0; i < 14; i++) {
        const fly = document.createElement("div");
        fly.className = "firefly-node";
        fly.style.left = `${Math.random() * 90 + 5}%`;
        fly.style.top = `${Math.random() * 80 + 10}%`;
        fly.style.animationDuration = `${Math.random() * 4 + 4}s`;
        fly.style.animationDelay = `${Math.random() * 3}s`;
        baliAtm.appendChild(fly);
      }
    }
  }

  setupAtmosphereControls() {
    const pauseBtn = document.getElementById("hero-pause-btn");
    pauseBtn?.addEventListener("click", () => {
      this.isSlideshowPaused = !this.isSlideshowPaused;
      pauseBtn.setAttribute("aria-label", this.isSlideshowPaused ? "Resume atmospheric slideshow" : "Pause atmospheric slideshow");
      pauseBtn.innerHTML = this.isSlideshowPaused
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
    });
  }

  setupDayNightToggle() {
    const toggleBtn = document.getElementById("day-night-toggle");
    const stored = sessionStorage.getItem("aetheria_theme");

    if (stored === "night") {
      document.body.classList.add("theme-night");
      if (toggleBtn) toggleBtn.innerHTML = "🌙";
    }

    toggleBtn?.addEventListener("click", () => {
      const isNight = document.body.classList.toggle("theme-night");
      sessionStorage.setItem("aetheria_theme", isNight ? "night" : "day");
      toggleBtn.innerHTML = isNight ? "🌙" : "☀️";
    });
  }

  setupParallaxDepth() {
    const depthLayer = document.querySelector(".hero-foreground-depth");
    if (!depthLayer) return;

    if (window.matchMedia("(pointer: fine)").matches) {
      window.addEventListener("mousemove", (e) => {
        if (!this.isHeroInView) return;
        const xOffset = (e.clientX / window.innerWidth - 0.5) * 14;
        const yOffset = (e.clientY / window.innerHeight - 0.5) * 10;
        depthLayer.style.transform = `translate3d(${-xOffset}px, ${-yOffset}px, 0)`;
      }, { passive: true });
    }
  }

  setupStickyPlanFab() {
    const fab = document.getElementById("sticky-plan-fab");
    const hero = document.getElementById("hero-section");
    if (!fab || !hero) return;

    window.addEventListener("scroll", () => {
      const heroBottom = hero.getBoundingClientRect().bottom;
      fab.classList.toggle("visible", heroBottom < 100);
    }, { passive: true });
  }

  setupLazySplitMap() {
    const mapContainer = document.getElementById("preview-sample-map");
    const section = document.getElementById("itinerary-preview-section");
    if (!mapContainer || !section) return;

    const observer = new IntersectionObserver(async (entries) => {
      if (entries[0].isIntersecting && !this.sampleMapLoaded) {
        this.sampleMapLoaded = true;
        observer.disconnect();

        // Ensure Leaflet is loaded
        if (!window.L) {
          for (let i = 0; i < 20; i++) {
            if (window.L) break;
            await new Promise((r) => setTimeout(r, 100));
          }
        }

        if (window.L) {
          this.initSampleMap(window.L, mapContainer);
        }
      }
    }, { rootMargin: "200px" });

    observer.observe(section);
  }

  initSampleMap(L, container) {
    this.sampleMap = L.map(container, {
      scrollWheelZoom: false,
      zoomControl: false,
    }).setView([35.0116, 135.7681], 12); // Kyoto, Japan

    L.control.zoom({ position: "bottomright" }).addTo(this.sampleMap);

    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
      attribution: "Tiles &copy; Esri",
      maxZoom: 18,
    }).addTo(this.sampleMap);

    // Sample spots from Kyoto
    const spots = [
      { name: "Fushimi Inari Shrine", lat: 34.9671, lon: 135.7727, day: 1 },
      { name: "Kiyomizu-dera Temple", lat: 34.9949, lon: 135.7850, day: 1 },
      { name: "Kinkaku-ji (Golden Pavilion)", lat: 35.0394, lon: 135.7292, day: 2 },
      { name: "Arashiyama Bamboo Grove", lat: 35.0170, lon: 135.6713, day: 3 },
      { name: "Gion District Dining", lat: 35.0037, lon: 135.7772, day: 4 },
    ];

    const markersGroup = L.featureGroup().addTo(this.sampleMap);

    const createPin = (colorHex) => {
      return L.divIcon({
        className: "gmap-custom-div-icon",
        html: `<div style="background-color:${colorHex}; width:24px; height:24px; border-radius:50%; border:2px solid #ffffff; box-shadow:0 3px 8px rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center; color:#fff; font-size:11px; font-weight:800;">📍</div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });
    };

    spots.forEach((s) => {
      const marker = L.marker([s.lat, s.lon], { icon: createPin("#1a73e8") });
      marker.bindPopup(`<strong>${s.name}</strong><br><small>Day ${s.day} Highlight</small>`);
      markersGroup.addLayer(marker);
    });

    try {
      this.sampleMap.fitBounds(markersGroup.getBounds(), { padding: [40, 40] });
    } catch {
      // ignore
    }

    // Connect day card clicks
    document.querySelectorAll(".preview-day-card").forEach((card) => {
      card.addEventListener("click", () => {
        document.querySelectorAll(".preview-day-card").forEach((c) => c.classList.remove("active"));
        card.classList.add("active");
        const dayNum = parseInt(card.getAttribute("data-day"), 10);
        const match = spots.find((s) => s.day === dayNum);
        if (match && this.sampleMap) {
          this.sampleMap.flyTo([match.lat, match.lon], 14, { duration: 1.2 });
        }
      });
    });
  }

  setupAgentSimulation() {
    const stations = [
      { id: "geospatial", name: "Geospatial Analyst", desc: "Resolving boundaries & transit nodes" },
      { id: "weather", name: "Meteorological Agent", desc: "Sampling 16-day climate models" },
      { id: "curator", name: "Attractions Specialist", desc: "Querying verified OSM places" },
      { id: "dining", name: "Culinary Consultant", desc: "Matching authentic regional cuisines" },
      { id: "budget", name: "Financial Controller", desc: "Balancing proportions & contingency" },
    ];

    const stationBoxes = document.querySelectorAll(".sim-station-box");
    const pauseBtn = document.getElementById("sim-pause-btn");

    const runSimulationStep = () => {
      if (this.isSimPaused) return;

      stationBoxes.forEach((box, idx) => {
        box.classList.toggle("active", idx === this.simStep);
        box.classList.toggle("completed", idx < this.simStep);
      });

      this.simStep++;
      if (this.simStep > stations.length) {
        this.simStep = 0;
      }
    };

    this.simInterval = setInterval(runSimulationStep, 2200);

    pauseBtn?.addEventListener("click", () => {
      this.isSimPaused = !this.isSimPaused;
      pauseBtn.textContent = this.isSimPaused ? "▶ Resume Preview" : "⏸ Pause Preview";
    });
  }

  setupMoodExplorer() {
    const moods = {
      kyoto: {
        img: "assets/img/hero-3-kyoto-1280.webp",
        title: "Kyoto, Japan",
        desc: "Ancient zen temples, quiet stone paths, and seasonal cherry blossom canopies.",
        best: "Mar – May",
        vibe: "Serene & Cultural",
        exp: "Fushimi Inari dawn hike",
      },
      alps: {
        img: "assets/img/hero-2-swiss-alps-1280.webp",
        title: "Swiss Alps, Switzerland",
        desc: "Glacial peaks, panoramic alpine rail, and pristine mountain air.",
        best: "Jun – Sep",
        vibe: "Adventure & Alpine",
        exp: "Glacier Express train",
      },
      santorini: {
        img: "assets/img/hero-1-santorini-1280.webp",
        title: "Santorini, Greece",
        desc: "White-washed cliffside villages overlooking cobalt caldera sunsets.",
        best: "May – Oct",
        vibe: "Romantic & Coastal",
        exp: "Oia caldera sunset dinner",
      },
      bali: {
        img: "assets/img/hero-4-bali-1280.webp",
        title: "Ubud, Bali",
        desc: "Emerald rice terraces, spiritual water temples, and lush tropical tranquility.",
        best: "Apr – Oct",
        vibe: "Tropical & Spiritual",
        exp: "Campuhan Ridge walk",
      },
      florence: {
        img: "assets/img/hero-7-florence-1280.webp",
        title: "Florence, Italy",
        desc: "Renaissance masterpieces, terracotta rooftops, and Tuscan evening aromas.",
        best: "Apr – Jun",
        vibe: "Artistic & Gastronomic",
        exp: "Duomo cupola ascent",
      },
    };

    const chips = document.querySelectorAll(".mood-chip");
    const bgImg = document.getElementById("mood-card-img");
    const titleEl = document.getElementById("mood-title");
    const descEl = document.getElementById("mood-desc");
    const bestEl = document.getElementById("mood-best");
    const vibeEl = document.getElementById("mood-vibe");
    const expEl = document.getElementById("mood-exp");
    const planBtn = document.getElementById("mood-plan-btn");

    chips.forEach((chip) => {
      chip.addEventListener("click", () => {
        chips.forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");

        const key = chip.getAttribute("data-mood");
        const data = moods[key];
        if (!data) return;

        if (bgImg) bgImg.src = data.img;
        if (titleEl) titleEl.textContent = data.title;
        if (descEl) descEl.textContent = data.desc;
        if (bestEl) bestEl.textContent = data.best;
        if (vibeEl) vibeEl.textContent = data.vibe;
        if (expEl) expEl.textContent = data.exp;
        if (planBtn) {
          planBtn.href = `/plan/?dest=${encodeURIComponent(data.title)}`;
          planBtn.textContent = `Plan ${data.title} ➔`;
        }
      });
    });
  }

  setupInteractivePreviews() {
    // Packing checklist interactive ticking
    document.querySelectorAll(".preview-packing-item").forEach((item) => {
      item.addEventListener("click", () => {
        item.classList.toggle("checked");
      });
    });
  }

  async fetchRealStats() {
    try {
      const res = await fetch("/api/stats");
      if (!res.ok) return;
      const data = await res.json();
      const count = data.total_trips_planned || 0;
      const statsEl = document.getElementById("hero-stats-count");
      // Only display stats honestly when count >= 10
      if (statsEl && count >= 10) {
        statsEl.textContent = `${count} expeditions planned`;
        statsEl.parentElement.style.display = "inline-flex";
      }
    } catch {
      // ignore
    }
  }
}

// Bootstrap on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.landingOrchestrator = new LandingOrchestrator();
});

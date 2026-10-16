/**
 * hero.js - Cinematic Background Carousel, Ken Burns Crossfades, and Scene Controls
 */

import { HERO_SCENES } from "./config.js";

export class HeroManager {
  constructor() {
    this.currentIndex = 0;
    this.isPlaying = true;
    this.intervalMs = 8000;
    this.timer = null;
    this.slides = [];
    this.dots = [];
    this.prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.container = document.getElementById("hero-bg-carousel");
    this.dotsContainer = document.getElementById("hero-dots");
    this.pausePlayBtn = document.getElementById("hero-pause-play");
    this.sceneTag = document.getElementById("hero-scene-tag");
    this.sceneNameEl = document.getElementById("hero-scene-name");

    this.init();
  }

  init() {
    if (!this.container) return;

    this.renderSlides();
    this.renderDots();
    this.bindEvents();

    if (!this.prefersReducedMotion) {
      this.startAutoplay();
    } else {
      this.isPlaying = false;
      this.updatePlayState();
    }

    this.updateScene(0);
  }

  renderSlides() {
    this.container.innerHTML = "";
    this.slides = HERO_SCENES.map((scene, idx) => {
      const slide = document.createElement("div");
      slide.className = `hero-slide ${idx === 0 ? "active" : ""}`;
      slide.setAttribute("role", "group");
      slide.setAttribute("aria-roledescription", "slide");
      slide.setAttribute("aria-label", `${idx + 1} of ${HERO_SCENES.length}: ${scene.name}`);

      const picture = document.createElement("picture");

      // WebP source
      const sourceWebp = document.createElement("source");
      sourceWebp.type = "image/webp";
      sourceWebp.srcset = `${scene.imgBase}-768.webp 768w, ${scene.imgBase}-1280.webp 1280w, ${scene.imgBase}-1920.webp 1920w`;
      sourceWebp.sizes = "100vw";

      // JPG fallback
      const sourceJpg = document.createElement("source");
      sourceJpg.type = "image/jpeg";
      sourceJpg.srcset = `${scene.imgBase}-768.jpg 768w, ${scene.imgBase}-1280.jpg 1280w, ${scene.imgBase}-1920.jpg 1920w`;
      sourceJpg.sizes = "100vw";

      const img = document.createElement("img");
      img.src = `${scene.imgBase}-1280.jpg`;
      img.alt = `${scene.name} landscape`;
      img.loading = idx === 0 ? "eager" : "lazy";
      img.decoding = idx === 0 ? "sync" : "async";

      picture.appendChild(sourceWebp);
      picture.appendChild(sourceJpg);
      picture.appendChild(img);
      slide.appendChild(picture);
      this.container.appendChild(slide);

      return slide;
    });
  }

  renderDots() {
    if (!this.dotsContainer) return;
    this.dotsContainer.innerHTML = "";
    this.dots = HERO_SCENES.map((scene, idx) => {
      const dot = document.createElement("button");
      dot.className = `scene-dot ${idx === 0 ? "active" : ""}`;
      dot.type = "button";
      dot.setAttribute("aria-label", `Switch scene to ${scene.name}`);
      dot.addEventListener("click", () => {
        this.goToScene(idx);
        if (this.isPlaying) this.resetAutoplay();
      });
      this.dotsContainer.appendChild(dot);
      return dot;
    });
  }

  bindEvents() {
    if (this.pausePlayBtn) {
      this.pausePlayBtn.addEventListener("click", () => {
        this.isPlaying = !this.isPlaying;
        if (this.isPlaying) {
          this.startAutoplay();
        } else {
          this.stopAutoplay();
        }
        this.updatePlayState();
      });
    }

    // Pause slideshow when page is in background
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.stopAutoplay();
      } else if (this.isPlaying && !this.prefersReducedMotion) {
        this.startAutoplay();
      }
    });
  }

  updatePlayState() {
    if (!this.pausePlayBtn) return;
    this.pausePlayBtn.setAttribute("aria-label", this.isPlaying ? "Pause background slideshow" : "Play background slideshow");
    const icon = this.pausePlayBtn.querySelector("span");
    if (icon) {
      icon.textContent = this.isPlaying ? "❚❚" : "▶";
    }
  }

  startAutoplay() {
    this.stopAutoplay();
    this.timer = setInterval(() => {
      this.nextScene();
    }, this.intervalMs);
  }

  stopAutoplay() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  resetAutoplay() {
    this.stopAutoplay();
    this.startAutoplay();
  }

  nextScene() {
    const nextIdx = (this.currentIndex + 1) % HERO_SCENES.length;
    this.goToScene(nextIdx);
  }

  goToScene(index) {
    if (index === this.currentIndex || index < 0 || index >= HERO_SCENES.length) return;

    this.slides[this.currentIndex]?.classList.remove("active");
    this.dots[this.currentIndex]?.classList.remove("active");

    this.currentIndex = index;
    this.slides[this.currentIndex]?.classList.add("active");
    this.dots[this.currentIndex]?.classList.add("active");

    this.updateScene(this.currentIndex);
    this.preloadNext(this.currentIndex);
  }

  updateScene(index) {
    const scene = HERO_SCENES[index];
    if (this.sceneNameEl && scene) {
      this.sceneNameEl.textContent = scene.name;
    }
  }

  preloadNext(currentIndex) {
    const nextIdx = (currentIndex + 1) % HERO_SCENES.length;
    const nextScene = HERO_SCENES[nextIdx];
    if (nextScene) {
      const link = document.createElement("link");
      link.rel = "prefetch";
      link.as = "image";
      link.href = `${nextScene.imgBase}-1280.webp`;
      document.head.appendChild(link);
    }
  }
}

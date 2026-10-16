# Aetheria Travel - Web Frontend

A cinematic, production-grade frontend for the AI Travel Planner Agent. Built with HTML5, modern CSS3, and vanilla JavaScript (ES modules) with **zero build step** and no runtime NPM dependencies.

---

## File Architecture

```
app/web/
├── index.html               # Semantic HTML5 entrypoint with SEO & JSON-LD
├── README.md                # This guide
├── assets/
│   ├── CREDITS.md           # Full image licenses & photographer attribution
│   ├── fonts/               # Self-hosted Manrope and Plus Jakarta Sans (.woff2)
│   └── img/                 # Responsive hero & destination images (WebP + JPG)
├── css/
│   ├── tokens.css           # Design tokens, fluid clamp typography, midnight palette
│   ├── base.css             # Font-face declarations, reset, skip link
│   ├── layout.css           # Navbar, responsive mobile drawer, footer
│   ├── components.css       # Buttons, form controls, chips, badges, toasts, skeletons
│   ├── print.css            # Clean, black-and-white print & PDF stylesheet
│   └── sections/
│       ├── hero.css         # Ken Burns crossfades, controls, quick planner
│       ├── planner.css      # Full interactive planner form & style picker
│       ├── generating.css   # Multi-agent real-time progress state
│       ├── results.css      # Results dashboard, itinerary accordion, stay, SVG budget
│       ├── editorial.css    # Featured destinations grid & how it works
│       ├── trips.css        # My Trips history & localStorage management
│       └── chat.css         # Interactive AI travel assistant & refine bubbles
├── js/
│   ├── config.js            # Configuration, API_BASE, pipeline stages, hero scenes
│   ├── utils.js             # XSS prevention (el helper), formatters, toast alerts
│   ├── state.js             # Client state, safe localStorage / sessionStorage store
│   ├── api.js               # Backend API client, SSE subscriber with polling fallback
│   ├── hero.js              # Cinematic background slideshow & accessible controls
│   ├── planner.js           # Form validation, chips, travel style mapping, duration
│   ├── progress.js          # Live agent pipeline progress tracker
│   ├── results.js           # Results renderer, accordion, SVG doughnut, timings
│   ├── map.js               # Lazy-loaded vendored Leaflet map with custom markers
│   ├── assistant.js         # Interactive chat assistant
│   ├── trips.js             # My Trips view manager
│   ├── ics.js               # RFC 5545 compliant .ics calendar event exporter
│   └── ui.js                # App orchestrator & hash router (#/, #/plan, #/trip/<slug>)
├── vendor/
│   └── leaflet/             # Self-hosted Leaflet 1.9.4 JS, CSS, and markers
└── data/
    └── sample-trip.json     # Authentic captured sample plan
```

---

## How to Run

1. Activate your virtual environment and start the FastAPI server:
   ```powershell
   .\venv\Scripts\Activate.ps1
   uvicorn app.api.main:app --port 8000
   ```
2. Open your browser and navigate to:
   ```
   http://localhost:8000/
   ```
   The site is served directly from FastAPI at `/` using `StaticFiles(html=True)`.

---

## How to Point to Another API Backend

By default, `js/config.js` uses `API_BASE = ""` to communicate with the same-origin FastAPI instance.

To target an external or remote API, set `window.__TRAVEL_CONFIG__` before loading `ui.js`, or configure it in `index.html`:
```html
<script>
  window.__TRAVEL_CONFIG__ = {
    API_BASE: "https://your-remote-api.com"
  };
</script>
```

---

## How to Update or Add Photography

1. Ensure the image license allows free distribution and self-hosting (Unsplash, Pexels, or Wikimedia Commons).
2. Generate responsive widths (1920px, 1280px, 768px) in both WebP and JPG formats:
   ```python
   from PIL import Image
   img = Image.open("your_photo.jpg")
   for w in (1920, 1280, 768):
       h = int(img.height * (w / img.width))
       resized = img.resize((w, h), Image.Resampling.LANCZOS)
       resized.save(f"app/web/assets/img/your-scene-{w}.webp", "WEBP", quality=82)
       resized.save(f"app/web/assets/img/your-scene-{w}.jpg", "JPEG", quality=85)
   ```
3. Update `app/web/assets/CREDITS.md` with URL, photographer, and license.
4. Add the scene reference into `HERO_SCENES` in `app/web/js/config.js`.

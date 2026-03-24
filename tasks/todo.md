# Pedkai TODO

## Pending

- [ ] **Light/Dark Mode — Inference & Polish**
  - AI inference button on divergence page fails in light mode (styling + error handling)
  - Test all pages end-to-end in light mode — check for missed hardcoded colors
  - Topology canvas: review node colors for contrast on light background
  - Login/tenant-select pages: currently always dark (brand decision?) — verify intentional
  - Sleeping cells, scorecard, incidents, feedback pages — visual QA in light mode
  - Consider system preference detection (`prefers-color-scheme`) as default

- [ ] **Topology — Device Icons**
  - Replace colored circles with device-type icons (gNodeB = pylon, switch = boxy computer, router, cell tower, etc.)
  - SVG or canvas-drawn icons, scaled with zoom
  - Maintain color coding per type as accent/background

- [ ] **Topology — Geographic Map Background**
  - Overlay topology graph on a geographic map so users see relationships in geo context
  - Nodes positioned by lat/lon from entity properties
  - Fallback to force-directed layout when coordinates unavailable

- [ ] **Research: Open-Source Mapping Libraries**
  - Investigate available options: Leaflet, OpenLayers, MapLibre GL, deck.gl, Mapbox (open-source parts)
  - Evaluate: canvas/WebGL rendering, tile sources (OpenStreetMap), clustering, performance with 10k+ nodes
  - Recommend best fit for Next.js static export + canvas topology overlay

- [ ] **Continuous Parquet Timeseries Pipeline**
  - Build a pipeline that continuously feeds Parquet timeseries data into the app via Kafka
  - Run indefinitely on cloud to observe how abeyance memory evolves over time
  - Simulate realistic telco KPI streams (throughput, latency, handover success, etc.)

- [ ] **Abeyance Memory — Observability & Steering**
  - Build test cases and diagnostic views to x-ray how abeyance memory evolves
  - Under-the-hood checks: memory growth, pattern convergence, anomaly recall accuracy
  - Identify levers to direct abeyance memory in the most beneficial direction
  - Dashboard or debug panel for operators to inspect memory state

- [ ] **LLM Inference Quality — Repetition & Token Control**
  - Reduce max_tokens from 1024 to 512 to prevent repetitive output
  - Add stop sequences to cut off repeated conclusions
  - Consider upgrading to 7B+ model when GPU available
  - Current 2B model: ~3 tok/s on ARM CPU, 9 min per inference — unusable for production
  - Investigate: streaming response to frontend, or pre-compute analyses in batch

- [ ] **LLM Inference Speed — Performance**
  - 9 minutes per inference on ARM CPU is not viable
  - Options: (a) GPU instance, (b) larger cloud provider, (c) external API (Gemini/Claude), (d) batch pre-computation during reconciliation run
  - Evaluate cost/performance tradeoff for each option

## Completed (2026-03-23)

- [x] ThemeContext with localStorage persistence
- [x] CSS variable overrides for `[data-theme="light"]`
- [x] Tailwind class overrides for hardcoded brand colors
- [x] Sun/Moon toggle in Navigation bar
- [x] Topology canvas theme-aware drawing
- [x] Historic analysis banner light-mode text fix
- [x] Navbar height matches logo at all breakpoints
- [x] Logo flush top-left corner

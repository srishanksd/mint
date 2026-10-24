# Implementation Plan - MINT: Autonomous Digital Venture Engine

## 1. Architecture Overview
- **Backend**: Python 3.11 + Flask (modular blueprint routes: `dashboard`, `experiments`, `chat`, `finance`, `media`, `storefront`).
- **Storage**: SQLite (`chronoforge/data/mint.db`) with clear schema for:
  - `experiments` (status, goal, budget, strategy, decisions, results)
  - `opportunities` (topic, evidence, demand score, business model, simulated flag)
  - `agent_logs` (agent name, status, input, output, explanation, timestamp)
  - `activity_feed` (event text, severity, timestamp)
  - `artifacts` (content drafts, scripts, images, audio, video files, guides)
  - `quality_checks` (passed/failed flags, issues list, recommendations)
  - `orders` (test purchase transactions, gross revenue, refunds, fees, timestamps)
  - `portfolio` (risk profile, allocations, reserve, reinvestment amounts, paper rebalancing suggestions)
  - `chat_messages` (role, content, actions taken, intent)
- **Frontend**: Vanilla HTML5, Neomorphic CSS (soft shadows, light background `#f0f3f6`, charcoal & muted teal accents), Vanilla JS + Chart.js (for financial breakdown and portfolio distribution).
- **Agents**:
  1. `OpportunityScout`: Searches public trends / curated market opportunities.
  2. `StrategyAgent`: Selects business model (content, digital product, affiliate, storefront) and audience.
  3. `MINTOrchestrator`: Controls execution flow, handles state transitions, pause/resume, feedback loops.
  4. `CreatorAgent`: Generates scripts, hooks, captions, SVG/Pillow image assets, guides/templates, and triggers FFmpeg assembly for short-form video.
  5. `QualityChecker`: Deterministic checks (disclosure check, claim check, length/format, broken links, originality).
  6. `CommercePublisher`: Test storefront with click tracking, test checkout, and draft export.
  7. `MeasurementAgent`: Aggregates metrics (views, clicks, orders, refunds, conversion rate).
  8. `FinanceAgent`: Deterministic accounting (gross revenue - fees - refunds - production costs = net profit, reserve calculations).
  9. `PortfolioManager`: Asset allocation (risk tiers: conservative, balanced, growth) with 100% reconciliation and paper rebalancing.
- **In-Dashboard Chat**: Processes commands (stop run, change audience, reduce budget, explain profit, change hook) and adjusts experiment parameters with audit logging.
- **Media Engine**: Local PIL/SVG generation + FFmpeg video stitching (color background/slides + audio tone/tts/subtitles).

## 2. Minimum Working End-to-End Flow
1. User clicks "Start Venture Experiment" with custom or preset parameters.
2. Scout finds 3 opportunities -> Strategy picks optimal model.
3. Creator crafts product/content + generates visual and video artifact using local FFmpeg.
4. Quality Checker verifies compliance and disclosures.
5. Item is deployed to the Local Test Storefront.
6. User triggers a test order / simulated traffic.
7. Measurement Agent tabulates results -> Finance Agent calculates net profit & reserve.
8. Portfolio Manager assigns surplus to simulated portfolio.
9. Orchestrator records recommendation for experiment #2.
10. Live interactive architecture graph highlights active nodes in real time, with clickable node inspection and persistent chat control.

## 3. Work Order Execution & Completed Milestones
- [x] Stage 1: Directory & requirements setup (`requirements.txt`, `.env.example`, `.gitignore`).
- [x] Stage 2: Database schema & models (`database.py`), core configuration (`config.py`).
- [x] Stage 3: Agent engines & orchestrator (`agents/`, `services/`).
- [x] Stage 4: Flask API endpoints & Blueprints (`routes/`).
- [x] Stage 5: Neomorphic UI Dashboard (`templates/`, `static/css/`, `static/js/`).
- [x] Stage 6: Media generation pipeline (PIL + FFmpeg).
- [x] Stage 7: Test storefront & commerce simulation.
- [x] Stage 8: Unit test suite for deterministic math, reserve, quality checks, and orchestrator.
- [x] Stage 9: End-to-end execution testing & Windows startup script (`run.bat`).
- [x] Stage 10: Complete documentation (`README.md`).
- [x] Milestone 11: Content Studio Engine (1080x1920 vertical multi-scene shorts via FFmpeg + Pillow, Piper TTS or silent captions, job packaging).
- [x] Milestone 12: Digital Products Catalog & Deliverables (auto-persisted to `digital_products`, preview, path-safe downloads).
- [x] Milestone 13: Affiliate Hub & Privacy-Preserving Redirects (opaque `/go/<token>`, SHA-256 hashed visitor attribution, FTC disclosures).
- [x] Milestone 14: Venture Portfolio view (combining paper surplus capital allocations with active products, offers & experiment track record).
- [x] Milestone 15: Persistent Light/Dark theme toggle with zero FOUC and Chart.js theme sync.
- [x] Milestone 16: Comprehensive QA — all 48 test cases passing cleanly.
- [x] Milestone 17: Test Pollution Elimination & Zero-Pollution Suite (`MINT_DB_PATH`, `MINT_GENERATED_DIR`, `MINT_DATA_DIR` dynamic runtime isolation).
- [x] Milestone 18: Safe Legacy Data Partitioning (Additive `is_test = 1` tagging for test products, test affiliate offers, and test content jobs without deleting records).
- [x] Milestone 19: Unified Shared Production Content Engine & Packaging (Structured outputs with `brief.json`, `script.json`, `storyboard.json`, `caption.txt`, `subtitles.srt`, `thumbnail.png`, `quality_report.json`, `package_manifest.json`, `final_short.mp4`).
- [x] Milestone 20: Meta Instagram Dual-Method Auth & Honest Status Diagnostics (`instagram_login` and `facebook_login`, cache bypass, zero token exposure in API responses).
- [x] Milestone 21: Design System Modernization — 5 Desktop Metric Cards on a Single Horizontal Row & Restrained Purple Palette (`#4f46e5`, `#4338ca`, `#818cf8`).
- [x] Milestone 22: Comprehensive 54-Test Verification Suite with verified test idempotence and 0 database/file mutations across runs.
- [x] Milestone 23: Digital Product Engine with Gemini curriculum generation, inspectable prompt drafting, and Playwright Chromium print-to-PDF rendering with strict 20-page limit and pypdf validation.
- [x] Milestone 24: Gumroad API v2 Integration (account verification, draft creation, accurate file-attachment status tracking) and segregated Affiliate Hub own-product management.
- [x] Milestone 25: Obsolete backup folder (`backups/before_ui_instagram_20261024`) safely deleted; complete 66-test verification suite passing cleanly with zero test pollution across runs.

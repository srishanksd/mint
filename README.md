# MINT — Autonomous Digital Venture Engine & Portfolio Allocator
*Personal Autonomous Venture Operating System*

MINT finds online business opportunities, creates test offers and marketing media, measures authentic results, audits regulatory compliance, calculates net unit economics, and allocates resulting surplus into a simulated paper investment portfolio.

---

## 1. Traceability & Metric Source Integrity (Zero-Fabrication Policy)

MINT does not invent numbers. Every displayed business metric has a traceable origin:

| Displayed Metric | Data Source & Traceability | Behavior When Data Is Absent |
|---|---|---|
| **Page Views** | Authentically logged to the `traffic_events` table upon landing page load (`event_type = 'view'`). 5-minute deduplication prevents bot inflation. | Displays `0 views` / `Awaiting traffic`. |
| **User Clicks & CTR** | Authentically logged when users click action buttons (`event_type = 'click'`). | Displays `0 clicks` / `0.0% CTR`. |
| **Sales & Revenue** | Real orders vs. sandbox test orders are recorded in the `orders` table (`is_test = 0` vs `1`). | Distinctly separated: `$0.00 real (X test transactions)`. |
| **Operational Spend** | Tracked in the `operational_costs` table with timestamps and cost categories. | Derived from recorded ledger; never hardcoded. |
| **Budget Used** | Written to `experiments.budget_used` when the pipeline completes. Backfilled from `finance_records.actual_spend` for older experiments. | `$0.00` when no cash was spent. |
| **Profit & Reserve** | Computed via deterministic double-entry formulas in `FinanceAgent` ($Gross - Fees - Refunds - Costs = Net$). | Locks compulsory 25% cash reserve only if net profit $> 0$. |
| **Portfolio Allocation** | Computed by `PortfolioManager` ensuring exact 100% allocation across target paper ETFs. | Paper simulation only; does not place live market orders. |
| **Opportunity Evidence** | Synthesized dynamically via active AI provider (Gemini/Mistral/Ollama) or marked as `curated_market_fixture`. | Labeled with transparent `source_type`. |

---

## 2. Autonomous Agent & Platform Architecture

1. **`Opportunity Scout`** ([`agents/opportunity_agent.py`](file:///D:/chronoforge/agents/opportunity_agent.py)): Dynamically generates contextual venture opportunities with market evidence via `AIService`, or returns explicitly labelled baseline market fixtures if unconfigured.
2. **`Strategy Agent`** ([`agents/strategy_agent.py`](file:///D:/chronoforge/agents/strategy_agent.py)): Evaluates unit economics against budget limits and **adapts based on previous experiment performance** (penalizes business models that previously failed or stalled).
3. **`MINT Orchestrator`** ([`agents/orchestrator.py`](file:///D:/chronoforge/agents/orchestrator.py)): Manages reliable pipeline execution, recording timestamps, checkpoints, and handling exceptions cleanly with `failed` / `completed` statuses.
4. **`Content Studio Engine`** ([`services/content_service.py`](file:///D:/chronoforge/services/content_service.py)): Generates 1080x1920 9:16 vertical video shorts via FFmpeg + Pillow multi-scene cards, AI or structured storyboards, Piper TTS integration or clean silent captions (never sine waves), and packages artifacts in `generated/content/<job_id>/`.
5. **`Product Builder`** ([`agents/product_builder.py`](file:///D:/chronoforge/agents/product_builder.py)): Generates actual digital deliverables (styled HTML playbooks & Markdown guides) automatically persisted to the `digital_products` catalog.
6. **`Affiliate Hub & Safe Redirect`** ([`routes/affiliates.py`](file:///D:/chronoforge/routes/affiliates.py)): Manages partner offers, transparent FTC disclosures, and safe opaque `/go/<token>` redirects with SHA-256 visitor hashing (no raw IPs stored).
7. **`Quality Checker`** ([`agents/quality_agent.py`](file:///D:/chronoforge/agents/quality_agent.py)): Deterministically audits regulatory disclosures (e.g. affiliate disclosures, claim safety, length).
8. **`Publishing Agent`** ([`services/social_service.py`](file:///D:/chronoforge/services/social_service.py)): Inspects YouTube and Instagram API status. When YouTube is connected, uploads as **private** video with full OAuth 2.0.
9. **`Measurement Agent`** ([`agents/measurement_agent.py`](file:///D:/chronoforge/agents/measurement_agent.py)): Evaluates funnel metrics strictly using logged observations. If views $< 25$, explicitly flags data as `insufficient_data`.
10. **`Finance Agent`** ([`agents/finance_agent.py`](file:///D:/chronoforge/agents/finance_agent.py)): Deterministically reconciles gross receipts, merchant fees, refunds, and operational spend to calculate realized net profit and compulsory 25% reserve. **Sandbox (test) orders are never included in real P&L.**
11. **`Portfolio Manager`** ([`agents/portfolio_manager.py`](file:///D:/chronoforge/agents/portfolio_manager.py)): Partitions eligible surplus into paper asset classes (Conservative, Balanced, Growth) with exact monetary and percentage reconciliation.
12. **`Venture Portfolio View`** ([`routes/portfolio.py`](file:///D:/chronoforge/routes/portfolio.py)): Combines historical venture track record with active digital products, affiliate performance, and paper allocations.
13. **`Chat Assistant`** ([`agents/chat_assistant.py`](file:///D:/chronoforge/agents/chat_assistant.py)): Enforces parameter safety bounds, executes revisions, and updates target audiences grounded in real SQLite state.

---

## 3. Directory Structure

```
D:\chronoforge\
├── app.py                      # Flask app factory, config & modular blueprint registration
├── config.py                   # Centralized paths, DB timeouts, provider configurations
├── database.py                 # SQLite schema with migrations, traffic tracking & thread-safe DB helpers
├── run.bat                     # Windows startup script
├── requirements.txt            # Python dependencies
├── .env.example                # Safe environment template with blank credentials (canonical)
├── agents/
│   ├── context_builder.py      # Real-time SQLite & service state aggregator for Control Assistant
│   ├── opportunity_agent.py    # Opportunity synthesis with AI or market fixtures
│   ├── strategy_agent.py       # Adaptive strategy engine learning from past runs
│   ├── orchestrator.py         # Thread-safe pipeline coordinator with exception handling
│   ├── creator_agent.py        # Copywriting and media asset generator
│   ├── product_builder.py      # Real digital guide & checklist packaging with catalog persistence
│   ├── quality_agent.py        # Deterministic compliance & disclosure auditor
│   ├── measurement_agent.py    # Funnel calculator based solely on logged traffic events & verified transactions
│   ├── finance_agent.py        # Deterministic accounting — real orders only (test orders excluded from P&L)
│   ├── portfolio_manager.py    # 100% balanced paper allocation engine with zero-surplus handling
│   └── chat_assistant.py       # Operational intelligence engine with context retrieval & action execution
├── services/
│   ├── ai_service.py           # Unified client (Gemini, Mistral, Ollama) with structured prompt & error reporting
│   ├── content_service.py      # Content Studio engine (1080x1920 vertical video compiler, Pillow & FFmpeg)
│   ├── media_service.py        # Pillow graphic generation & FFmpeg silent short video compiler
│   └── social_service.py       # Official YouTube Data API v3 (cached) & Instagram Graph API connectors
├── routes/
│   ├── dashboard.py            # Overview & live-state APIs with progression metrics & media serving
│   ├── content_studio.py       # Content Studio UI, job queuing, execution & safe file serving
│   ├── products.py             # Digital Products catalog, detail pages & safe downloads
│   ├── affiliates.py           # Affiliate offer management, stats & safe opaque /go/<token> redirects
│   ├── portfolio.py            # Venture Portfolio & paper capital allocations
│   ├── experiments.py          # Venture execution lifecycle endpoints with input validation
│   ├── chat.py                 # Interactive chat and action command route
│   ├── storefront.py           # Storefront with real view/click logging, order processing & refunds
│   └── youtube_auth.py         # Full YouTube OAuth 2.0 flow (authorize, callback, upload, disconnect)
├── templates/
│   ├── dashboard.html          # Poppins neomorphic UI with global nav and live architecture layout
│   ├── studio.html             # Content Studio short-form video generation & preview
│   ├── products.html           # Digital products catalog
│   ├── product_detail.html     # Product package preview & download
│   ├── affiliates.html         # Affiliate partner offer hub & compliance disclosures
│   ├── portfolio.html          # Venture Portfolio & paper surplus allocator
│   └── storefront.html         # Landing page that logs genuine views & checkout clicks
├── static/
│   ├── css/dashboard.css       # Clean neomorphic styles, Dark/Light tokens & Poppins typography
│   └── js/dashboard.js         # Non-overlapping polling, live node states, theme toggle & verified platform details
├── generated/                  # Rendered MP4 videos, graphics, digital products, and content jobs
├── tests/
│   └── test_engines.py         # 48 tests covering real metrics, studio, affiliates, products, OAuth & security
└── data/                       # SQLite persistence (mint.db)
```

---

## 4. Getting Started on Windows

### 1. Prerequisites
- Python 3.10+
- FFmpeg installed on PATH (verified: ffmpeg 9.0.1 present on this machine)

### 2. Configure Environment (Optional Keys)
Copy `.env.example` to `.env`:
```bat
copy .env.example .env
```
Edit `.env` with your credentials. Minimal config to run locally (no AI key needed for basic operation):
```env
SECRET_KEY=change-this-to-a-random-string
OAUTHLIB_INSECURE_TRANSPORT=1   # Required for local HTTP OAuth testing
```
To enable live AI model chat, add:
```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```
*(If no key is configured, MINT will honestly indicate that it is awaiting credentials while all local media, accounting, and storefront features remain fully functional).*

### 3. Launch Application
Double-click `run.bat` or run:
```bat
python app.py
```
Open your browser to:
- **Operating Dashboard**: `http://127.0.0.1:5000`
- **Sandbox Storefront**: `http://127.0.0.1:5000/storefront`

---

## 5. YouTube Integration (OAuth 2.0)

MINT integrates with the YouTube Data API v3 for private video uploads. The full OAuth flow is implemented in [`routes/youtube_auth.py`](file:///D:/chronoforge/routes/youtube_auth.py).

### Setup (one-time)
1. Place your Google OAuth 2.0 **Web application** client secrets JSON at the path set in `.env`:
   ```env
   YOUTUBE_CLIENT_SECRETS_FILE=path/to/client_secret_*.json
   ```
2. Register this **Authorized Redirect URI** in [Google Cloud Console → OAuth Clients](https://console.cloud.google.com/auth/clients):
   ```
   http://127.0.0.1:5000/oauth2callback
   ```
3. Add your Google account as a **Test User** at [Google Cloud Console → Audience](https://console.cloud.google.com/auth/audience) while the app is in test mode.

### Connecting
1. Start MINT and open `http://127.0.0.1:5000`
2. In the **YouTube** section, click **Connect YouTube**
3. Complete the Google sign-in flow
4. Once connected, the dashboard shows your channel name and enables private video upload

### Security Properties
- Client secrets are **never** sent to the browser
- Access tokens and refresh tokens are stored **server-side only** in the `oauth_tokens` database table
- All uploads are forced to `privacyStatus: private` — cannot be overridden from the UI
- CSRF protection: OAuth state token is generated per session and validated before token exchange
- PKCE (`code_verifier`) is stored in the server session and passed during token exchange

---

## 6. Instagram Integration

Instagram publishing uses the Meta Graph API with comprehensive dual-flow support (`instagram_login` and `facebook_login`). Status is clearly diagnosed and verified in the dashboard without hanging.

Configure in `.env`:
```env
# Mode selection: "instagram_login" or "facebook_login"
INSTAGRAM_LOGIN_METHOD=instagram_login

# Credentials:
INSTAGRAM_ACCOUNT_ID=your_ig_user_or_business_account_id
INSTAGRAM_ACCESS_TOKEN=your_meta_access_token

# Optional scope declaration:
INSTAGRAM_GRANTED_SCOPES=instagram_business_basic,instagram_business_content_publish
```

### Verified Security & Health Features:
- **No Infinite "Checking..." State**: UI status checks always cleanly terminate with full diagnostic indicators and a manual "Check Connection" button with cache bypass (`?refresh=1`).
- **Zero Token Leakage**: The `/api/social/instagram/status` API never includes raw credentials or tokens.
- **Scope Verification**: Prevents publishing attempts if the token lacks Meta's required permissions (`instagram_business_content_publish` or `instagram_content_publish`).
- **Local Media Guard**: Meta cannot fetch localhost URLs (`http://127.0.0.1`). Published videos must be hosted at a publicly reachable HTTPS URL or tunnel; local-only runs honestly declare `media_hosting_required`.

---

## 7. Digital Product Engine (Gemini + Chromium PDF + Gumroad)

MINT provides an autonomous Digital Product Engine in the **Digital Products** workspace (`/products`). It transforms product ideas into verified, print-ready PDF packages without manual layout work.

### End-to-End Generation Pipeline
1. **Idea Validation & Brief Derivation**: Validates core concepts and generates structured curriculum briefs (title, audience, learning outcomes, section breakdowns, deliverables).
2. **Inspectable Gemini Prompt**: Formulates a detailed prompt enforcing strict editorial rules (zero fabricated case studies, zero invented percentages, clean Markdown). The prompt is inspectable and editable directly in the UI before generation.
3. **Gemini Generation**: Direct integration with Google Gemini (`gemini-2.0-flash` or configured model via `GEMINI_API_KEY`). Reports honest API / quota errors if credentials are missing or exhausted.
4. **Print-Ready Semantic HTML**: Generates styled HTML with Poppins typography, navy text (`#0f172a`), restrained purple accents (`#4f46e5`, `#3730a3`), callout boxes, and responsive tables.
5. **Chromium Print-to-PDF**: Renders PDF deliverables using Playwright headless Chromium with custom page headers and footers.
6. **20-Page Constraint & Validation**: Uses `pypdf` to count actual pages. Enforces a strict upper bound of 20 pages; flags any document that exceeds the boundary.
7. **Packaging**: Creates an organized directory under `generated/products/<product-slug>/` containing:
   - `product.pdf` (printable deliverable)
   - `source.md` (clean markdown)
   - `content.json` (brief metadata)
   - `generation_prompt.md` (exact prompt sent to Gemini)
   - `render.html` (standalone styled HTML)
   - `manifest.json` (SHA-256 integrity hashes for all files)
   - `quality_report.json` (audit scores & page counts)
8. **Catalog Persistence**: Records product state in SQLite `digital_products`.
9. **Gumroad Integration**: Synchronizes metadata to Gumroad via API v2. Accurately distinguishes `Draft created on Gumroad — PDF attachment required` from `Published with PDF attached`.

---

## 8. Affiliate Hub & Commerce Segregation

Affiliate Hub (`/affiliates`) maintains strict separation between external partner offers and internal digital products:
- **Third-Party Affiliate Offers**: Real merchant destination URLs, user-configured commissions, FTC disclosure copy, and privacy-conscious click attribution (`/go/<token>`).
- **My MINT / Gumroad Products (Own Products)**: 100% venture margin, clearly tagged as `Own Product`, linking to local PDF downloads and verified Gumroad product pages. Never manufactured into fake affiliate offers with artificial commissions.

---

## 9. Test Isolation & Zero-Pollution Policy

MINT adheres to strict zero-pollution automated testing:
- **Environment Overrides**: Tests run against isolated temporary databases (`MINT_DB_PATH`) and temporary directories (`MINT_GENERATED_DIR`, `MINT_DATA_DIR`).
- **Zero Production Mutations**: Executing `pytest` never inserts synthetic records into `data/mint.db` or generates test files in `generated/`.
- **Safe Legacy Segregation**: Legacy test artifacts are partitioned using `is_test = 1` and excluded from public storefronts, active catalogs, and production financial reports without destroying user records.

---

## 10. Running Automated Verification Tests

66 comprehensive tests covering real agent engines, YouTube OAuth flow, storefront integrity, finance separation, security (path traversal, XSS input), Instagram safeguards, Gemini curriculum brief generation, Playwright Chromium PDF rendering, max 20-page limits, Gumroad API synchronization, and Affiliate Hub segregation:

```bat
python -m pytest tests/test_engines.py -v
```

Expected output: **66 passed**.

---

## 11. Security Notes

- **`.env`** — Never commit this file. It is in `.gitignore`.
- **`client_secret*.json`** — Never commit. It is in `.gitignore`.
- OAuth tokens and Gumroad credentials are stored only server-side and never exposed in client JSON or JavaScript.
- The media serving route (`/api/media/<category>/<filename>`) and product download route (`/api/products/<id>/download`) validate against path traversal attacks using `.resolve()` parent comparison.
- All user-supplied strings rendered in the dashboard pass through `escapeHtml()` to prevent XSS.
- Storefront orders have 15-second duplicate throttling and price bounds ($0.01–$5,000).

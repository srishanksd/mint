# MINT — Autonomous Digital Venture Engine & Portfolio Allocator
*Personal Autonomous Venture Operating System*

MINT discovers online business opportunities, creates digital product deliverables and marketing media, measures authentic results, audits regulatory compliance, calculates net unit economics, and allocates resulting surplus into a simulated paper investment portfolio.

---

## 1. Traceability & Metric Source Integrity (Zero-Fabrication Policy)

MINT does not invent numbers. Every displayed business metric has a traceable origin:

| Displayed Metric | Data Source & Traceability | Behavior When Data Is Absent |
|---|---|---|
| **Page Views** | Authentically logged to the `traffic_events` table upon landing page load (`event_type = 'view'`). 5-minute deduplication prevents bot inflation. | Displays `0 views` / `Awaiting traffic`. |
| **User Clicks & CTR** | Authentically logged when users click action buttons (`event_type = 'click'`). | Displays `0 clicks` / `0.0% CTR`. |
| **Sales & Revenue** | Real orders vs. sandbox test orders are recorded in the `orders` table (`is_test = 0` vs `1`). | Distinctly separated: `$0.00 real (X test transactions)`. |
| **Operational Spend** | Tracked in the `operational_costs` table with timestamps and cost categories. | Derived from recorded ledger; never hardcoded. |
| **Budget Used** | Written to `experiments.budget_used` when the pipeline completes. | `$0.00` when no cash was spent. |
| **Profit & Reserve** | Computed via deterministic double-entry formulas in `FinanceAgent` ($Gross - Fees - Refunds - Costs = Net$). | Locks compulsory 25% cash reserve only if net profit $> 0$. |
| **Portfolio Allocation** | Computed by `PortfolioManager` ensuring exact 100% allocation across target paper ETFs. | Paper simulation only; does not place live market orders. |
| **Opportunity Evidence** | Synthesized dynamically via local Ollama inference or marked as `curated_market_fixture`. | Labeled with transparent `source_type`. |

---

## 2. Autonomous Agent & Platform Architecture

1. **`Opportunity Scout`** (`agents/opportunity_agent.py`): Dynamically discovers contextual digital product opportunities with market evidence via local Ollama (`llama3.2`) or local deterministic market fixtures.
2. **`Strategy Agent`** (`agents/strategy_agent.py`): Evaluates unit economics against budget limits and adapts based on historical venture performance.
3. **`MINT Orchestrator`** (`agents/orchestrator.py`): Manages pipeline execution, recording timestamps, checkpoints, and exception handling.
4. **`YouTube Clips & OpenShorts Agent`** (`agents/youtube_clips_agent.py`): Orchestrates YouTube channel discovery, OpenShorts MCP tool execution (`http://127.0.0.1:8000/mcp`), and local 9:16 vertical video clipping with `faster-whisper` and FFmpeg.
5. **`Product Builder & Digital Product Engine`** (`agents/product_builder.py`, `services/digital_product_engine.py`): Generates genuine digital product deliverables (PDF ebooks, styled HTML guides, JSON manifests) persisted to the `digital_products` catalog and synchronized with Gumroad.
6. **`Quality Checker`** (`agents/quality_agent.py`): Deterministically audits regulatory disclosures, claim safety, and deliverable completeness.
7. **`Publishing Agent`** (`services/social_service.py`): Manages YouTube OAuth 2.0 uploads and Instagram Graph API publishing with Cloudinary public media hosting diagnostics.
8. **`Measurement Agent`** (`agents/measurement_agent.py`): Evaluates funnel metrics strictly using logged traffic events and verified transactions.
9. **`Finance Agent`** (`agents/finance_agent.py`): Deterministically reconciles gross receipts, merchant fees, refunds, and operational spend. Sandbox test orders are distinctly separated from real P&L.
10. **`Portfolio Manager`** (`agents/portfolio_manager.py`): Partitions eligible surplus into paper asset classes (Conservative, Balanced, Growth) with exact monetary and percentage reconciliation.
11. **`Venture Control Assistant MCP Server`** (`services/mint_mcp_server.py`, `services/mcp_agent_client.py`): Native MCP 2.x server exposing operational control tools to AI clients with persistent SQLite audit logs in `mcp_audit_logs`.

---

## 3. Canonical Project Structure

```text
D:\chronoforge\
├── app.py                      # Flask application factory and blueprint registration
├── config.py                   # Central configuration, SQLite paths, and environment settings
├── database.py                 # SQLite schema with idempotent migrations and helpers
├── requirements.txt            # Declared application dependencies
├── run.bat                     # Windows startup script
├── .env                        # Local configuration file (never committed)
├── .gitignore                  # Git ignore rules for caches, media, and credentials
├── client_secret_*.json        # Google OAuth 2.0 client credentials
├── agents/                     # Agent decision and orchestration modules
├── services/                   # Business logic, MCP client/server, media engines, social services
├── routes/                     # Clean Flask route blueprints
├── templates/                  # Professional minimalist Jinja templates
├── static/                     # CSS stylesheets and vanilla JavaScript
├── tests/                      # Automated test suite (test_engines.py)
├── data/
│   └── mint.db                 # Primary SQLite database
└── generated/
    ├── content/
    │   ├── youtube_clips/      # Canonical location for generated vertical clips
    │   └── instagram/          # Generated Instagram carousel slides
    ├── images/                 # AI-generated image assets
    └── products/               # Digital product deliverables (PDFs, HTML guides)
```

---

## 4. Environment Configuration (`.env`)

MINT uses a single local `.env` configuration file located at the project root.

```bash
# Core Application
PORT=5000
HOST=127.0.0.1
FLASK_SECRET_KEY=your_secure_random_key_here

# Local AI Reasoning (Ollama)
AI_PROVIDER=ollama
OLLAMA_ENDPOINT=http://localhost:11434
OLLAMA_MODEL=llama3.2

# OpenShorts MCP Server (Self-Hosted Video Clipping)
OPENSHORTS_MCP_URL=http://127.0.0.1:8000/mcp

# Image Generation & Hosting
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token
CLOUDINARY_CLOUD_NAME=your_cloudinary_cloud_name
CLOUDINARY_API_KEY=your_cloudinary_api_key
CLOUDINARY_API_SECRET=your_cloudinary_api_secret

# Instagram Graph API
META_GRAPH_API_VERSION=v22.0
INSTAGRAM_ACCOUNT_ID=your_instagram_business_account_id
INSTAGRAM_ACCESS_TOKEN=your_instagram_user_access_token

# Gumroad Commerce Integration
GUMROAD_ACCESS_TOKEN=your_gumroad_access_token
GUMROAD_AUTO_PUBLISH=0

# YouTube OAuth Configuration
YOUTUBE_CLIENT_SECRET_JSON=client_secret_xxxx.json
YOUTUBE_CLIENT_ID=your_google_client_id
YOUTUBE_CLIENT_SECRET=your_google_client_secret
YOUTUBE_REDIRECT_URI=http://127.0.0.1:5000/api/youtube/callback
```

---

## 5. Local Setup & Execution

### Prerequisites
- Python 3.11+
- FFmpeg installed and accessible in system `PATH` (verify with `ffmpeg -version`)
- Ollama running locally with `ollama pull llama3.2`

### Installation
```powershell
cd D:\chronoforge
python -m pip install -r requirements.txt
```

### Running the Application
```powershell
python app.py
```
Or run via Windows batch file:
```powershell
run.bat
```
Navigate to **`http://127.0.0.1:5000`** in your browser.

---

## 6. Automated Testing

Run the full automated test suite (100% pass):
```powershell
cd D:\chronoforge
python -m pytest tests/test_engines.py -v
```

To run a dry-run consistency and reference audit on generated files and SQLite records:
```powershell
python -c "from services.cleanup_service import CleanupService; import json; print(json.dumps(CleanupService.get_inventory(), indent=2))"
```
Or query `http://127.0.0.1:5000/api/system/audit` in your browser.

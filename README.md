# MINT — Autonomous Digital Venture Engine & Portfolio Allocator
*Personal Autonomous Venture Operating System*

MINT discovers online business opportunities, creates digital product deliverables and marketing media, measures authentic results, audits regulatory compliance, calculates net unit economics, and allocates resulting surplus into a simulated paper investment portfolio.
---
[DEMO Video Link](https://drive.google.com/drive/folders/1qHYv8ox8Sa3aO63r7lh2wxtJEs6se30o?usp=sharing)
---
[![Architecture diagram](https://gitdiagram.com/diagram-badge.svg)](https://gitdiagram.com/srishanksd/mint?utm_source=readme&utm_medium=badge)
---
```mermaid
flowchart TD

subgraph group_platform["Platform"]
  node_app["Flask App<br/>app.py"]
  node_db[("SQLite Database<br/>database.py")]
  node_experiments_route["Experiment Routes<br/>experiments.py"]
  node_dashboard_route["Dashboard Routes<br/>dashboard.py"]
  node_chat_route["Chat Routes<br/>chat.py"]
  node_chat["Contextual Assistant<br/>chat_assistant.py"]
end

subgraph group_venture["Venture Pipeline"]
  node_orchestrator["Venture Orchestrator<br/>orchestrator.py"]
  node_opportunity["Opportunity Scout<br/>opportunity_agent.py"]
  node_strategy["Strategy Agent<br/>strategy_agent.py"]
  node_creator["Marketing Creator<br/>creator_agent.py"]
  node_quality["Compliance Checker<br/>quality_agent.py"]
end

subgraph group_products["Products & Commerce"]
  node_product_builder["Product Builder<br/>product_builder.py"]
  node_engine["Digital Product Engine<br/>digital_product_engine.py"]
  node_gumroad["Gumroad Commerce<br/>gumroad_service.py"]
end

subgraph group_media["Media & Publishing"]
  node_content["Content Studio<br/>content_service.py"]
  node_social["Social Publisher<br/>social_service.py"]
  node_youtube_auth["YouTube OAuth<br/>youtube_auth.py"]
  node_clips_route["Clips Routes<br/>youtube_clips.py"]
  node_clips_agent["Clips Agent<br/>youtube_clips_agent.py"]
  node_local_clipper["Local Clipper<br/>local_clipper_service.py"]
  node_scheduler["YouTube Scheduler<br/>youtube_scheduler_service.py"]
end

subgraph group_insight["Measurement & Allocation"]
  node_measurement["Measurement Agent<br/>measurement_agent.py"]
  node_finance["Finance Agent<br/>finance_agent.py"]
  node_portfolio["Paper Portfolio<br/>portfolio_manager.py"]
end

node_user(("MINT User"))
node_external_ai{{"AI Providers"}}
node_social_platforms{{"Social Platforms"}}
node_gumroad_external{{"Gumroad API"}}
node_openshorts{{"OpenShorts MCP"}}

node_user -->|"Uses"| node_app
node_app -->|"Initializes"| node_db
node_app -->|"Registers"| node_experiments_route
node_app -->|"Registers"| node_dashboard_route
node_app -->|"Registers"| node_chat_route
node_app -->|"Registers"| node_clips_route

node_experiments_route -->|"Starts experiment"| node_orchestrator

node_orchestrator -->|"Discovers candidates"| node_opportunity
node_orchestrator -->|"Selects strategy"| node_strategy
node_orchestrator -->|"Creates promotion"| node_creator
node_orchestrator -->|"Builds deliverable"| node_product_builder
node_orchestrator -->|"Audits deliverable"| node_quality
node_orchestrator -->|"Measures funnel"| node_measurement
node_orchestrator -->|"Reconciles finances"| node_finance
node_orchestrator -->|"Allocates surplus"| node_portfolio

node_product_builder -->|"Renders product"| node_engine
node_engine -->|"Generates content"| node_external_ai
node_engine -->|"Syncs catalog"| node_gumroad
node_gumroad -->|"Uses commerce API"| node_gumroad_external

node_creator -.->|"Creates media"| node_content
node_content -->|"Publishes media"| node_social
node_social -->|"Publishes to"| node_social_platforms
node_youtube_auth -->|"Provides OAuth tokens"| node_social

node_clips_route -->|"Runs clipping"| node_clips_agent
node_clips_agent -->|"Renders local clips"| node_local_clipper
node_clips_agent -->|"Queues publishing"| node_scheduler
node_clips_agent -->|"Invokes MCP tools"| node_openshorts

node_chat_route -->|"Handles chat"| node_chat
node_chat -->|"Reads live context"| node_db
node_chat -->|"Requests reasoning"| node_external_ai

node_measurement -->|"Reads events"| node_db
node_finance -->|"Reads ledger"| node_db
node_portfolio -.->|"Records allocation"| node_db
node_dashboard_route -->|"Reads metrics"| node_db

click node_app "https://github.com/srishanksd/mint/blob/main/app.py"
click node_db "https://github.com/srishanksd/mint/blob/main/database.py"
click node_experiments_route "https://github.com/srishanksd/mint/blob/main/routes/experiments.py"
click node_dashboard_route "https://github.com/srishanksd/mint/blob/main/routes/dashboard.py"
click node_chat_route "https://github.com/srishanksd/mint/blob/main/routes/chat.py"
click node_chat "https://github.com/srishanksd/mint/blob/main/agents/chat_assistant.py"
click node_orchestrator "https://github.com/srishanksd/mint/blob/main/agents/orchestrator.py"
click node_opportunity "https://github.com/srishanksd/mint/blob/main/agents/opportunity_agent.py"
click node_strategy "https://github.com/srishanksd/mint/blob/main/agents/strategy_agent.py"
click node_creator "https://github.com/srishanksd/mint/blob/main/agents/creator_agent.py"
click node_product_builder "https://github.com/srishanksd/mint/blob/main/agents/product_builder.py"
click node_engine "https://github.com/srishanksd/mint/blob/main/services/digital_product_engine.py"
click node_quality "https://github.com/srishanksd/mint/blob/main/agents/quality_agent.py"
click node_gumroad "https://github.com/srishanksd/mint/blob/main/services/gumroad_service.py"
click node_content "https://github.com/srishanksd/mint/blob/main/services/content_service.py"
click node_social "https://github.com/srishanksd/mint/blob/main/services/social_service.py"
click node_youtube_auth "https://github.com/srishanksd/mint/blob/main/routes/youtube_auth.py"
click node_clips_route "https://github.com/srishanksd/mint/blob/main/routes/youtube_clips.py"
click node_clips_agent "https://github.com/srishanksd/mint/blob/main/agents/youtube_clips_agent.py"
click node_local_clipper "https://github.com/srishanksd/mint/blob/main/services/local_clipper_service.py"
click node_scheduler "https://github.com/srishanksd/mint/blob/main/services/youtube_scheduler_service.py"
click node_measurement "https://github.com/srishanksd/mint/blob/main/agents/measurement_agent.py"
click node_finance "https://github.com/srishanksd/mint/blob/main/agents/finance_agent.py"
click node_portfolio "https://github.com/srishanksd/mint/blob/main/agents/portfolio_manager.py"

classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337
classDef toneIndigo fill:#e0e7ff,stroke:#4f46e5,stroke-width:1.5px,color:#312e81

class node_app,node_db,node_experiments_route,node_dashboard_route,node_chat_route,node_chat,node_user toneBlue
class node_orchestrator,node_opportunity,node_strategy,node_creator,node_quality toneAmber
class node_product_builder,node_engine,node_gumroad toneMint
class node_content,node_social,node_youtube_auth,node_clips_route,node_clips_agent,node_local_clipper,node_scheduler toneRose
class node_measurement,node_finance,node_portfolio,node_external_ai,node_social_platforms,node_gumroad_external,node_openshorts toneIndigo
```
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
4. **`YouTube Clips & OpenShorts Agent`** (`agents/youtube_clips_agent.py`): Orchestrates YouTube channel discovery, OpenShorts MCP tool execution, and local 9:16 vertical video clipping with `faster-whisper` and FFmpeg.
5. **`Product Builder & Digital Product Engine`** (`agents/product_builder.py`, `services/digital_product_engine.py`): Generates genuine digital product deliverables (PDF ebooks, styled HTML guides, JSON manifests) persisted to the `digital_products` catalog and synchronized with Gumroad.
6. **`Quality Checker`** (`agents/quality_agent.py`): Deterministically audits regulatory disclosures, claim safety, and deliverable completeness.
7. **`Social Publishing Engine`** (`services/social_service.py`): Manages YouTube OAuth 2.0 uploads and Instagram Graph API publishing with Cloudinary public media hosting diagnostics.
8. **`Measurement Agent`** (`agents/measurement_agent.py`): Evaluates funnel metrics strictly using logged traffic events and verified transactions.
9. **`Finance Agent`** (`agents/finance_agent.py`): Deterministically reconciles gross receipts, merchant fees, refunds, and operational spend. Sandbox test orders are distinctly separated from real P&L.
10. **`Portfolio Manager`** (`agents/portfolio_manager.py`): Partitions eligible surplus into paper asset classes (Conservative, Balanced, Growth) with exact monetary and percentage reconciliation.
11. **`Context Builder & In-Dashboard Chat`** (`agents/context_builder.py`, `agents/chat_assistant.py`): Feeds live database metrics directly to conversational reasoning with zero hallucinations.
12. **`Venture Control MCP Server & Clients`** (`services/mint_mcp_server.py`, `services/mcp_agent_client.py`, `services/clipper_mcp_client.py`, `services/local_clipper_service.py`): Native Model Context Protocol (MCP) server exposing operational venture control tools to external AI clients with persistent SQLite audit logs in `mcp_audit_logs`.

---

## 3. Canonical Project Structure

```text
mint/
├── app.py                             # Flask application factory and blueprint registration
├── config.py                          # Central configuration, SQLite paths, and environment settings
├── database.py                        # SQLite schema with idempotent migrations and helpers
├── requirements.txt                   # Declared application dependencies
├── run.bat                            # Windows 1-click startup script
├── PLAN.md                            # Comprehensive milestone implementation plan
├── README.md                          # Full architectural and setup documentation
├── .env                               # Local configuration file (git-ignored)
├── .gitignore                         # Git ignore rules for caches, media, and credentials
│
├── agents/                            # Autonomous decision & orchestration engines
│   ├── chat_assistant.py              # In-dashboard contextual consultation assistant
│   ├── context_builder.py             # Live state and metrics aggregator for AI context
│   ├── creator_agent.py               # Generates copy, social hooks, and promotional content
│   ├── finance_agent.py               # Deterministic unit economics and cash reserve accounting
│   ├── measurement_agent.py           # Funnel analytics (views, clicks, orders, conversion rates)
│   ├── opportunity_agent.py           # Market demand and trend analysis
│   ├── orchestrator.py                # Main workflow coordinator and pipeline state machine
│   ├── portfolio_manager.py           # 100% reconciled surplus allocation across risk profiles
│   ├── product_builder.py             # Digital product deliverable generation trigger
│   ├── quality_agent.py               # Compliance, safety, and regulatory audit engine
│   ├── strategy_agent.py              # Business model and audience selection
│   └── youtube_clips_agent.py         # Autonomous channel discovery and viral clipping agent
│
├── routes/                            # Modular Flask route blueprints
│   ├── chat.py                        # In-dashboard AI copilot endpoints
│   ├── content_studio.py              # Video & social content generation routes
│   ├── dashboard.py                   # Main overview, venture metrics, and architecture graph
│   ├── experiments.py                 # Venture experiment creation and execution lifecycle
│   ├── portfolio.py                   # Paper investment portfolio and surplus breakdown
│   ├── products.py                    # Digital products catalog, downloads, and Gumroad sync
│   ├── youtube_auth.py                # Google OAuth 2.0 flow and channel analytics
│   └── youtube_clips.py               # Viral clips generation, preview, queue, and direct publish
│
├── services/                          # Business logic, integration engines, and MCP servers
│   ├── ai_image_service.py            # Cloudflare Workers AI (FLUX.1 Schnell) image generation
│   ├── ai_service.py                  # Multi-model LLM abstraction (Ollama, Gemini, Mistral)
│   ├── cleanup_service.py             # File system and database orphan reconciler
│   ├── clipper_mcp_client.py          # OpenShorts MCP tool integration client
│   ├── content_service.py             # Multi-scene video synthesis via FFmpeg + Pillow
│   ├── digital_product_engine.py      # PDF eBook and interactive HTML guide rendering engine
│   ├── gumroad_service.py             # Gumroad API v2 commerce integration
│   ├── instagram_marketing_service.py # Instagram Graph API photo and carousel publisher
│   ├── local_clipper_service.py       # Local Faster-Whisper + FFmpeg intelligent clip extractor
│   ├── mcp_agent_client.py            # Client interface for MCP tool invocation
│   ├── media_hosting_service.py       # Cloudinary HTTPS media hosting for external webhooks
│   ├── media_service.py               # Core PIL/SVG media generation primitives
│   ├── mint_mcp_server.py             # Native Model Context Protocol (MCP) server
│   ├── social_service.py              # Social media publishing and scheduling dispatcher
│   ├── youtube_clipping_service.py    # YouTube source video downloader and audio extractor
│   └── youtube_scheduler_service.py   # Twice-daily peak audience publishing scheduler
│
├── static/                            # Frontend assets
│   ├── css/
│   │   └── dashboard.css              # Neomorphic responsive design system
│   └── js/
│       └── dashboard.js               # Reactive client controllers, Chart.js, and polling
│
├── templates/                         # Server-rendered Jinja2 UI templates
│   ├── dashboard.html                 # Main venture operations command center
│   ├── portfolio.html                 # Paper asset allocation and surplus dashboard
│   ├── product_detail.html            # Individual product deliverable inspection and preview
│   ├── products.html                  # Catalog of created digital guides and deliverables
│   ├── studio.html                    # Creative studio for multi-scene shorts and carousels
│   └── youtube_clips.html             # Video clipping suite, schedule queue, and player
│
├── tests/                             # Automated test suite
│   └── test_engines.py                # Comprehensive end-to-end engine verification suite
│
├── data/                              # SQLite persistence (git-ignored)
│   └── mint.db                        # Primary relational database
│
└── generated/                         # Output artifacts and media deliverables (git-ignored)
    ├── content/
    │   ├── youtube_clips/             # Rendered 9:16 vertical short videos
    │   └── instagram/                 # Generated Instagram carousel slides
    ├── images/                        # AI-generated marketing illustrations
    └── products/                      # Compiled PDF eBooks, source Markdown, and HTML
```

---

## 4. Environment Configuration (`.env`)

MINT reads configuration from a local `.env` file at the repository root:

```bash
# Core Application
PORT=5000
HOST=127.0.0.1
FLASK_SECRET_KEY=your_secure_random_key_here

# Local AI Reasoning (Ollama / Gemini / Mistral)
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
- Ollama running locally (`ollama pull llama3.2`) or API keys configured in `.env`

### Installation
```powershell
pip install -r requirements.txt
```

### Running the Application
```powershell
python app.py
```
*Or simply double-click **`run.bat`**.*

Access the dashboard at **`http://127.0.0.1:5000`**.

---

## 6. Automated Testing & Verification

Run the full automated test suite:
```powershell
python -m pytest tests/test_engines.py -v
```

To run a consistency and reference audit on generated files and SQLite records:
```powershell
python -c "from services.cleanup_service import CleanupService; import json; print(json.dumps(CleanupService.get_inventory(), indent=2))"
```
Or query `http://127.0.0.1:5000/api/system/audit` in your browser.

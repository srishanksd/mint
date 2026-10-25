# Implementation Plan — MINT Architecture Consolidation & Cleanup

## 1. Consolidated Architecture Overview
- **Backend**: Python 3.11 + Flask (modular blueprints: `dashboard`, `experiments`, `chat`, `products`, `portfolio`, `youtube_auth`, `youtube_clips`).
- **Storage**: SQLite (`chronoforge/data/mint.db`) with idempotent schema migrations and durable audit logging (`mcp_audit_logs`).
- **AI & Reasoning**: Local Ollama (`llama3.2`) with state-grounded local deterministic fallback. Zero external hosted LLM dependencies.
- **Video Clipping**: 
  - Authoritative MCP Client (`ClipperMCPClient`) communicating with self-hosted OpenShorts MCP server (`http://127.0.0.1:8000/mcp`).
  - Provider B Local Free Clipper (`LocalClipperService`) using `faster-whisper` and FFmpeg 9:16 vertical transcoding (1080x1920 blur padding + centered crop).
  - Canonical output directory: `generated/content/youtube_clips/<job_id>/`.
- **Commerce**: Real Gumroad synchronization (`GumroadService`), PDF/HTML digital product creation (`DigitalProductEngine`), and authentic financial reconciliation.
- **Social Integrations**: Official YouTube Data API v3 OAuth 2.0 and Instagram Graph API with Cloudinary HTTPS media hosting diagnostics.
- **Frontend**: Professional minimalist CSS, vanilla JavaScript, no heavy frontend frameworks.

## 2. Completed Milestones
- [x] **Milestone 1: Clean Canonical Project Structure**: Established standard responsibilities across `agents/`, `services/`, `routes/`, `templates/`, `static/`, `tests/`, `data/`, and `generated/`.
- [x] **Milestone 2: Complete LumiClip Removal**: Purged LumiClip service, alias routes, credit consumption messages, and `.env` settings while preserving historical project rows as read-only archive.
- [x] **Milestone 3: OpenShorts MCP & Free Local Clipper Integration**: Authoritative MCP client and local whisper+FFmpeg engine with automated twice-daily scheduling.
- [x] **Milestone 4: Removal of Affiliate Hub & Storefront**: Deleted obsolete routes and templates; removed storefront links and marketing claims.
- [x] **Milestone 5: Reference Audit & Generated Folder Cleanup**: Implemented comprehensive inventory in `CleanupService`; removed orphaned duplicate files and obsolete empty directories while preserving real deliverables and image assets.
- [x] **Milestone 6: Single Canonical Environment**: Single `.env` configuration; retired `.env.example`.
- [x] **Milestone 7: Comprehensive Test Verification**: Full test suite updated and passing 100% (114 tests) with zero live database pollution.

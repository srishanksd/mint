import sqlite3
import json
from datetime import datetime
from pathlib import Path
import config

DB_PATH = config.DB_PATH

def get_db_connection():
    # Set busy_timeout to 30000ms to safely handle concurrent operations
    # Respects dynamic config.DB_PATH for test isolation
    target_path = getattr(config, "DB_PATH", DB_PATH)
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Experiments table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        goal TEXT NOT NULL,
        business_model TEXT NOT NULL,
        target_audience TEXT NOT NULL,
        budget_limit REAL NOT NULL DEFAULT 50.0,
        status TEXT NOT NULL DEFAULT 'draft',
        hypothesis TEXT,
        recommended_action TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # Candidate Opportunities
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        title TEXT NOT NULL,
        niche TEXT NOT NULL,
        business_model TEXT NOT NULL,
        evidence TEXT NOT NULL,
        demand_score INTEGER NOT NULL,
        competition_level TEXT NOT NULL,
        selected INTEGER DEFAULT 0,
        is_simulated INTEGER DEFAULT 1,
        source_type TEXT DEFAULT 'simulated_seed',
        source_ref TEXT,
        confidence TEXT DEFAULT 'low_unverified',
        is_verified INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Agent execution runs and states
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        agent_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'waiting',
        input_summary TEXT,
        output_summary TEXT,
        decision_reason TEXT,
        warning_or_error TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Chronological Activity feed
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_feed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        agent_name TEXT NOT NULL,
        message TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info',
        timestamp TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Artifacts (Video, Image, Digital Products, Scripts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        artifact_type TEXT NOT NULL,
        title TEXT NOT NULL,
        hook TEXT,
        content_text TEXT,
        file_path TEXT,
        call_to_action TEXT,
        disclaimer TEXT,
        meta_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Quality Checks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quality_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        artifact_id INTEGER,
        passed INTEGER NOT NULL,
        score REAL NOT NULL,
        issues_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id),
        FOREIGN KEY (artifact_id) REFERENCES artifacts (id)
    )
    """)

    # Commerce Test Events & Orders
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        customer_email TEXT NOT NULL,
        product_title TEXT NOT NULL,
        gross_amount REAL NOT NULL,
        fee_amount REAL NOT NULL,
        is_refunded INTEGER DEFAULT 0,
        refund_amount REAL DEFAULT 0.0,
        is_test INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Real Traffic Events (Page Views and Link/Button Clicks)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS traffic_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        event_type TEXT NOT NULL, -- 'view' or 'click'
        source TEXT NOT NULL,     -- 'storefront', 'video_link', 'affiliate_redirect'
        referrer TEXT,
        ip_hash TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Operational & Production Costs (Actual cash spend vs estimated compute)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS operational_costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        cost_category TEXT NOT NULL, -- 'media_rendering', 'domain_hosting', 'advertising', 'api_usage'
        cost_type TEXT NOT NULL DEFAULT 'cash_expense', -- 'cash_expense' or 'estimated_compute'
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Finances & Accounting
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS finance_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        starting_budget REAL NOT NULL,
        actual_spend REAL NOT NULL,
        gross_revenue REAL NOT NULL,
        fees REAL NOT NULL,
        refunds REAL NOT NULL,
        net_profit REAL NOT NULL,
        required_reserve REAL NOT NULL,
        reinvestment_allocated REAL NOT NULL,
        surplus_available REAL NOT NULL,
        is_simulated INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Portfolio Allocation
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        risk_profile TEXT NOT NULL,
        time_horizon TEXT NOT NULL,
        total_surplus REAL NOT NULL,
        allocations_json TEXT NOT NULL,
        rebalancing_notes TEXT,
        is_simulated INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Chat interaction history
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER,
        conversation_id TEXT DEFAULT 'default',
        sender TEXT NOT NULL,
        message TEXT NOT NULL,
        intent_detected TEXT,
        action_taken TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments (id)
    )
    """)

    # Schema migrations: Add missing columns safely
    cursor.execute("PRAGMA table_info(opportunities)")
    opp_cols = [row[1] for row in cursor.fetchall()]
    if "source_type" not in opp_cols:
        cursor.execute("ALTER TABLE opportunities ADD COLUMN source_type TEXT DEFAULT 'simulated_seed'")
    if "source_ref" not in opp_cols:
        cursor.execute("ALTER TABLE opportunities ADD COLUMN source_ref TEXT DEFAULT NULL")
    if "confidence" not in opp_cols:
        cursor.execute("ALTER TABLE opportunities ADD COLUMN confidence TEXT DEFAULT 'low_unverified'")
    if "is_verified" not in opp_cols:
        cursor.execute("ALTER TABLE opportunities ADD COLUMN is_verified INTEGER DEFAULT 0")

    cursor.execute("PRAGMA table_info(operational_costs)")
    cost_cols = [row[1] for row in cursor.fetchall()]
    if "cost_type" not in cost_cols:
        cursor.execute("ALTER TABLE operational_costs ADD COLUMN cost_type TEXT DEFAULT 'cash_expense'")

    cursor.execute("PRAGMA table_info(experiments)")
    exp_cols = [row[1] for row in cursor.fetchall()]
    if "budget_used" not in exp_cols:
        cursor.execute("ALTER TABLE experiments ADD COLUMN budget_used REAL DEFAULT NULL")

    # OAuth token storage (server-side only; never exposed to frontend)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS oauth_tokens (
        id          INTEGER PRIMARY KEY,
        provider    TEXT    NOT NULL UNIQUE,
        token_json  TEXT    NOT NULL,
        created_at  TEXT    DEFAULT (datetime('now')),
        updated_at  TEXT    DEFAULT (datetime('now'))
    )
    """)

    # General activity log (used by upload events and other system events)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type  TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now'))
    )
    """)

    # Content generation studio jobs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS content_jobs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id   INTEGER,
        product_id      INTEGER,
        title           TEXT NOT NULL,
        product_type    TEXT NOT NULL DEFAULT 'mint_product',
        angle           TEXT NOT NULL DEFAULT 'relatable_problem',
        audience        TEXT NOT NULL,
        problem         TEXT NOT NULL,
        product_facts   TEXT NOT NULL,
        destination_url TEXT,
        cta             TEXT,
        aspect_ratio    TEXT DEFAULT '9:16',
        target_duration INTEGER DEFAULT 15,
        status          TEXT NOT NULL DEFAULT 'queued',
        progress_pct    INTEGER DEFAULT 0,
        current_step    TEXT DEFAULT 'Job queued',
        error_message   TEXT,
        disclosure_text TEXT,
        output_dir      TEXT,
        video_path      TEXT,
        thumbnail_path  TEXT,
        script_json     TEXT,
        quality_json    TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """)

    # Digital Products Catalog & Deliverables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS digital_products (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id       INTEGER,
        slug                TEXT UNIQUE NOT NULL,
        title               TEXT NOT NULL,
        product_type        TEXT NOT NULL DEFAULT 'guide',
        audience            TEXT NOT NULL,
        value_proposition   TEXT NOT NULL,
        description         TEXT NOT NULL,
        contents_json       TEXT NOT NULL DEFAULT '[]',
        version             TEXT DEFAULT '1.0.0',
        price               REAL NOT NULL DEFAULT 14.99,
        currency            TEXT DEFAULT 'USD',
        status              TEXT NOT NULL DEFAULT 'published',
        file_path           TEXT,
        preview_path        TEXT,
        product_intent      TEXT DEFAULT 'guide',
        gumroad_publish_status TEXT DEFAULT 'unpublished',
        gumroad_attachment_status TEXT DEFAULT 'missing',
        gumroad_edit_url    TEXT DEFAULT NULL,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    )
    """)

    # Affiliate Offers (strictly user-configured, with required disclosures)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS affiliate_offers (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        token           TEXT UNIQUE NOT NULL,
        name            TEXT NOT NULL,
        vendor          TEXT NOT NULL,
        niche           TEXT NOT NULL,
        audience        TEXT NOT NULL,
        description     TEXT NOT NULL,
        destination_url TEXT NOT NULL,
        commission_rate TEXT NOT NULL,
        price           REAL DEFAULT 0.0,
        currency        TEXT DEFAULT 'USD',
        region          TEXT DEFAULT 'Global',
        notes           TEXT,
        disclosure_copy TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'active',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """)

    # Privacy-conscious outbound affiliate click events (hashed visitor ID, never raw IP)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS affiliate_clicks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        offer_id        INTEGER NOT NULL,
        job_id          INTEGER,
        experiment_id   INTEGER,
        source_page     TEXT,
        visitor_hash    TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        FOREIGN KEY (offer_id) REFERENCES affiliate_offers (id)
    )
    """)

    # Verified / manually entered affiliate conversions with explicit evidence source
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS affiliate_conversions (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        offer_id            INTEGER NOT NULL,
        amount              REAL NOT NULL,
        commission_earned   REAL NOT NULL,
        source_type         TEXT NOT NULL DEFAULT 'manual_entry',
        evidence_ref        TEXT,
        is_test             INTEGER DEFAULT 0,
        created_at          TEXT NOT NULL,
        FOREIGN KEY (offer_id) REFERENCES affiliate_offers (id)
    )
    """)

    # AI-generated image assets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS image_assets (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt          TEXT NOT NULL,
        negative_prompt TEXT,
        aspect_ratio    TEXT DEFAULT '1:1',
        resolution      TEXT DEFAULT '1024x1024',
        style           TEXT DEFAULT 'photorealistic',
        provider        TEXT NOT NULL DEFAULT 'gemini',
        model           TEXT NOT NULL,
        file_path       TEXT,
        file_size_bytes INTEGER DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'completed',
        error_message   TEXT,
        is_test         INTEGER DEFAULT 0,
        created_at      TEXT NOT NULL
    )
    """)

    # Instagram marketing posts and carousels
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS instagram_posts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id          INTEGER,
        post_type           TEXT NOT NULL DEFAULT 'single',
        title               TEXT NOT NULL,
        caption             TEXT NOT NULL,
        hashtags            TEXT,
        cta                 TEXT,
        image_paths_json    TEXT NOT NULL DEFAULT '[]',
        hosted_urls_json    TEXT DEFAULT '[]',
        target_audience     TEXT,
        marketing_angle     TEXT,
        visual_style        TEXT,
        aspect_ratio        TEXT DEFAULT '1:1',
        include_brand_logo  INTEGER DEFAULT 0,
        show_product_info   INTEGER DEFAULT 1,
        status              TEXT NOT NULL DEFAULT 'draft',
        media_id            TEXT,
        container_id        TEXT,
        published_at        TEXT,
        error_message       TEXT,
        is_test             INTEGER DEFAULT 0,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        FOREIGN KEY (product_id) REFERENCES digital_products (id)
    )
    """)

    # Safe additive schema migrations for test isolation & legacy classification
    cursor.execute("PRAGMA table_info(content_jobs)")
    job_cols = [row[1] for row in cursor.fetchall()]
    if "is_test" not in job_cols:
        cursor.execute("ALTER TABLE content_jobs ADD COLUMN is_test INTEGER DEFAULT 0")

    cursor.execute("PRAGMA table_info(digital_products)")
    prod_cols = [row[1] for row in cursor.fetchall()]
    if "is_test" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN is_test INTEGER DEFAULT 0")
    if "pdf_path" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN pdf_path TEXT DEFAULT NULL")
    if "page_count" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN page_count INTEGER DEFAULT 0")
    if "file_size_bytes" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN file_size_bytes INTEGER DEFAULT 0")
    if "quality_score" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN quality_score REAL DEFAULT 0.0")
    if "quality_report_json" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN quality_report_json TEXT DEFAULT NULL")
    if "prompt_text" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN prompt_text TEXT DEFAULT NULL")
    if "idea_prompt" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN idea_prompt TEXT DEFAULT NULL")
    if "gumroad_id" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_id TEXT DEFAULT NULL")
    if "gumroad_url" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_url TEXT DEFAULT NULL")
    if "gumroad_sync_status" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_sync_status TEXT DEFAULT 'not_synced'")
    if "gumroad_sync_message" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_sync_message TEXT DEFAULT NULL")
    if "gumroad_synced_at" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_synced_at TEXT DEFAULT NULL")
    if "auto_publish_gumroad" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN auto_publish_gumroad INTEGER DEFAULT 0")
    if "product_intent" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN product_intent TEXT DEFAULT 'guide'")
    if "gumroad_publish_status" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_publish_status TEXT DEFAULT 'unpublished'")
    if "gumroad_attachment_status" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_attachment_status TEXT DEFAULT 'missing'")
    if "gumroad_edit_url" not in prod_cols:
        cursor.execute("ALTER TABLE digital_products ADD COLUMN gumroad_edit_url TEXT DEFAULT NULL")

    cursor.execute("PRAGMA table_info(affiliate_offers)")
    aff_cols = [row[1] for row in cursor.fetchall()]
    if "is_test" not in aff_cols:
        cursor.execute("ALTER TABLE affiliate_offers ADD COLUMN is_test INTEGER DEFAULT 0")

    cursor.execute("PRAGMA table_info(affiliate_clicks)")
    click_cols = [row[1] for row in cursor.fetchall()]
    if "is_test" not in click_cols:
        cursor.execute("ALTER TABLE affiliate_clicks ADD COLUMN is_test INTEGER DEFAULT 0")

    # YouTube clips table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS youtube_clips (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id              INTEGER,
        source_channel_name TEXT,
        source_channel_id   TEXT,
        source_video_ref    TEXT,
        source_file_path    TEXT NOT NULL,
        rights_confirmed    INTEGER DEFAULT 0,
        clip_title          TEXT NOT NULL,
        clip_description    TEXT,
        hashtags            TEXT,
        aspect_ratio        TEXT DEFAULT '9:16',
        start_time_sec      REAL NOT NULL DEFAULT 0.0,
        end_time_sec        REAL NOT NULL DEFAULT 15.0,
        duration_sec        REAL DEFAULT 15.0,
        output_path         TEXT,
        file_size_bytes     INTEGER DEFAULT 0,
        status              TEXT DEFAULT 'draft',
        error_message       TEXT,
        is_test             INTEGER DEFAULT 0,
        created_at          TEXT NOT NULL
    )
    """)

    # YouTube twice-daily schedule table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS youtube_schedules (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        enabled                 INTEGER DEFAULT 0,
        timezone                TEXT DEFAULT 'Asia/Kolkata',
        slot_1_time             TEXT DEFAULT '10:00',
        slot_2_time             TEXT DEFAULT '18:00',
        audience_timing_source  TEXT DEFAULT 'user_configured_studio',
        last_run_at             TEXT,
        next_run_at             TEXT,
        status                  TEXT DEFAULT 'idle',
        updated_at              TEXT NOT NULL
    )
    """)

    # YouTube scheduled posts queue
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS youtube_scheduled_posts (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id                 INTEGER NOT NULL,
        destination_channel_id  TEXT,
        scheduled_time          TEXT NOT NULL,
        target_slot             TEXT DEFAULT 'slot_1',
        status                  TEXT NOT NULL DEFAULT 'queued',
        youtube_video_id        TEXT,
        youtube_video_url       TEXT,
        publish_at_iso          TEXT,
        error_message           TEXT,
        attempt_count           INTEGER DEFAULT 0,
        published_at            TEXT,
        is_test                 INTEGER DEFAULT 0,
        created_at              TEXT NOT NULL,
        updated_at              TEXT NOT NULL,
        FOREIGN KEY (clip_id) REFERENCES youtube_clips (id)
    )
    """)

    # Chat messages additive migration
    cursor.execute("PRAGMA table_info(chat_messages)")
    chat_cols = [row[1] for row in cursor.fetchall()]
    if "conversation_id" not in chat_cols:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN conversation_id TEXT DEFAULT 'default'")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id)")

    # ── LumiClip & YouTube Source Channels Tables ────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS youtube_source_channels (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id          TEXT UNIQUE NOT NULL,
        title               TEXT NOT NULL,
        handle              TEXT,
        thumbnail_url       TEXT,
        custom_url          TEXT,
        rights_confirmed    INTEGER DEFAULT 0,
        last_scanned_at     TEXT,
        is_active           INTEGER DEFAULT 1,
        is_test             INTEGER DEFAULT 0,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS youtube_discovered_videos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id          TEXT NOT NULL,
        video_id            TEXT UNIQUE NOT NULL,
        title               TEXT NOT NULL,
        description         TEXT,
        published_at        TEXT,
        thumbnail_url       TEXT,
        status              TEXT DEFAULT 'discovered',
        lumiclip_project_id TEXT,
        is_test             INTEGER DEFAULT 0,
        created_at          TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lumiclip_projects (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id          TEXT UNIQUE NOT NULL,
        video_url           TEXT NOT NULL,
        video_title         TEXT,
        source_channel_id   TEXT,
        source_channel_name TEXT,
        status              TEXT DEFAULT 'processing',
        progress_pct        INTEGER DEFAULT 0,
        clips_count         INTEGER DEFAULT 0,
        raw_response_json   TEXT,
        error_message       TEXT,
        is_test             INTEGER DEFAULT 0,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    )
    """)

    # YouTube clips additive columns for LumiClip integration
    cursor.execute("PRAGMA table_info(youtube_clips)")
    clip_cols = [row[1] for row in cursor.fetchall()]
    if "lumiclip_clip_id" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN lumiclip_clip_id TEXT")
    if "lumiclip_project_id" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN lumiclip_project_id TEXT")
    if "virality_score" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN virality_score REAL DEFAULT 0.0")
    if "virality_reason" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN virality_reason TEXT")
    if "thumbnail_url" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN thumbnail_url TEXT")
    if "approved_at" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN approved_at TEXT")
    if "source_video_url" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN source_video_url TEXT")
    if "youtube_video_id" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN youtube_video_id TEXT")
    if "youtube_video_url" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN youtube_video_url TEXT")
    if "published_at" not in clip_cols:
        cursor.execute("ALTER TABLE youtube_clips ADD COLUMN published_at TEXT")

    # YouTube schedules additive columns
    cursor.execute("PRAGMA table_info(youtube_schedules)")
    sched_cols = [row[1] for row in cursor.fetchall()]
    if "auto_publish" not in sched_cols:
        cursor.execute("ALTER TABLE youtube_schedules ADD COLUMN auto_publish INTEGER DEFAULT 0")
    if "max_daily_posts" not in sched_cols:
        cursor.execute("ALTER TABLE youtube_schedules ADD COLUMN max_daily_posts INTEGER DEFAULT 2")
    if "queue_target" not in sched_cols:
        cursor.execute("ALTER TABLE youtube_schedules ADD COLUMN queue_target INTEGER DEFAULT 6")
    if "destination_channel_id" not in sched_cols:
        cursor.execute("ALTER TABLE youtube_schedules ADD COLUMN destination_channel_id TEXT")
    if "destination_channel_name" not in sched_cols:
        cursor.execute("ALTER TABLE youtube_schedules ADD COLUMN destination_channel_name TEXT")

    # Safe idempotent migration of identified automated test records in database
    _classify_legacy_test_records(cursor)

    conn.commit()
    conn.close()

def _classify_legacy_test_records(cursor):
    """
    Idempotent migration:
    Flags automated test records as is_test=1 and archives them from public views
    without deleting any files or records. Preserves real user work.
    """
    try:
        # 1. Archive automated test products (repeated Solopreneur Sprint Pack with no real deliverable file)
        cursor.execute("""
            UPDATE digital_products
            SET is_test = 1, status = 'archived'
            WHERE (title = 'Solopreneur Sprint Pack' OR slug LIKE 'solopreneur-sprint-pack%')
              AND (file_path IS NULL OR file_path = '')
        """)

        # 2. Archive automated test affiliate offers (SuperTool Pro test fixtures)
        cursor.execute("""
            UPDATE affiliate_offers
            SET is_test = 1, status = 'archived'
            WHERE name = 'SuperTool Pro' AND vendor = 'SuperCorp'
              AND destination_url = 'https://supercorp.com/affiliate-target'
        """)

        # 3. Flag automated test content jobs (Automated Short Test / Test Studio Short)
        cursor.execute("""
            UPDATE content_jobs
            SET is_test = 1
            WHERE title IN ('Test Studio Short', 'Automated Short Test')
        """)
    except Exception:
        pass

def log_activity(experiment_id, agent_name, message, severity="info"):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO activity_feed (experiment_id, agent_name, message, severity, timestamp) VALUES (?, ?, ?, ?, ?)",
        (experiment_id, agent_name, message, severity, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def update_agent_status(experiment_id, agent_name, status, input_summary="", output_summary="", decision_reason="", warning_or_error=""):
    conn = get_db_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute("SELECT id FROM agent_runs WHERE experiment_id = ? AND agent_name = ?", (experiment_id, agent_name))
    row = cur.fetchone()
    if row:
        cur.execute("""
            UPDATE agent_runs
            SET status = ?, input_summary = ?, output_summary = ?, decision_reason = ?, warning_or_error = ?, updated_at = ?
            WHERE id = ?
        """, (status, input_summary, output_summary, decision_reason, warning_or_error, now, row["id"]))
    else:
        cur.execute("""
            INSERT INTO agent_runs (experiment_id, agent_name, status, input_summary, output_summary, decision_reason, warning_or_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (experiment_id, agent_name, status, input_summary, output_summary, decision_reason, warning_or_error, now))
    conn.commit()
    conn.close()

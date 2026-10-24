"""
agents/context_builder.py
Builds a focused, current snapshot of MINT system state for the Control Assistant.
Pulls data from the actual SQLite database and integration services — never invents values.
"""

import json
from datetime import datetime
from database import get_db_connection
from services.social_service import YouTubeService, InstagramService
from services.ai_service import AIService
from services.ai_image_service import AIImageService
from services.media_hosting_service import MediaHostingService
from services.gumroad_service import GumroadService


def build_context(experiment_id=None):
    """
    Returns a comprehensive dict describing current MINT operational state.
    Pulls real records from SQLite, Cloudflare Workers AI status, Meta Instagram,
    YouTube OAuth & schedule queue, and digital products catalog.
    Never includes secrets, tokens, or raw credentials.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # ── Resolve experiment ────────────────────────────────────────────────────
    if experiment_id:
        cur.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
    else:
        cur.execute(
            "SELECT * FROM experiments WHERE id IN "
            "(SELECT experiment_id FROM artifacts) ORDER BY id DESC LIMIT 1"
        )
    exp_row = cur.fetchone()
    if not exp_row:
        cur.execute("SELECT * FROM experiments ORDER BY id DESC LIMIT 1")
        exp_row = cur.fetchone()

    # ── Catalog Products & Deliverables ───────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM digital_products WHERE is_test = 0")
    prod_cnt = cur.fetchone()["cnt"] or 0
    cur.execute("""
        SELECT id, title, slug, price, status, page_count, product_intent,
               gumroad_id, gumroad_url, gumroad_sync_status, gumroad_publish_status, gumroad_attachment_status,
               file_path, pdf_path
        FROM digital_products
        WHERE is_test = 0
        ORDER BY id DESC LIMIT 5
    """)
    recent_prods = [dict(r) for r in cur.fetchall()]

    # ── Affiliate Offers & Traffic ───────────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM affiliate_offers WHERE is_test = 0")
    aff_cnt = cur.fetchone()["cnt"] or 0
    cur.execute("SELECT COUNT(*) as clicks FROM affiliate_clicks WHERE is_test = 0")
    aff_clicks = cur.fetchone()["clicks"] or 0
    cur.execute("SELECT COUNT(*) as convs, SUM(commission_earned) as earned FROM affiliate_conversions WHERE is_test = 0")
    aff_conv_row = cur.fetchone()
    aff_convs = aff_conv_row["convs"] or 0
    aff_earned = round(aff_conv_row["earned"] or 0.0, 2)

    # ── AI Image Assets ───────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM image_assets WHERE is_test = 0")
    image_cnt = cur.fetchone()["cnt"] or 0
    cur.execute("SELECT id, prompt, aspect_ratio, provider, model, status, created_at FROM image_assets WHERE is_test = 0 ORDER BY id DESC LIMIT 3")
    recent_images = [dict(r) for r in cur.fetchall()]

    # ── Instagram Marketing Posts ─────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM instagram_posts WHERE is_test = 0")
    ig_post_cnt = cur.fetchone()["cnt"] or 0
    cur.execute("SELECT id, title, post_type, status, media_id, published_at FROM instagram_posts WHERE is_test = 0 ORDER BY id DESC LIMIT 3")
    recent_ig_posts = [dict(r) for r in cur.fetchall()]

    # ── YouTube Clips & Scheduler ─────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM youtube_clips WHERE is_test = 0")
    clips_cnt = cur.fetchone()["cnt"] or 0
    cur.execute("SELECT * FROM youtube_schedules ORDER BY id ASC LIMIT 1")
    sched_row = cur.fetchone()
    schedule_cfg = dict(sched_row) if sched_row else {
        "enabled": 0, "timezone": "UTC", "slot_1_time": "10:00", "slot_2_time": "18:00", "audience_timing_source": "user_configured_studio"
    }
    cur.execute("SELECT COUNT(*) as cnt FROM youtube_scheduled_posts WHERE status IN ('queued', 'uploading', 'scheduled_api')")
    scheduled_posts_cnt = cur.fetchone()["cnt"] or 0

    # ── Content Studio Legacy Jobs ────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM content_jobs WHERE status = 'completed' AND is_test = 0")
    content_cnt = cur.fetchone()["cnt"] or 0

    # ── Integrations Status (no secrets) ──────────────────────────────────────
    yt_status = YouTubeService.get_status()
    ig_status = InstagramService.get_status()
    ai_status = AIService.get_provider_status()
    ai_image_status = AIImageService.get_status()
    media_hosting = MediaHostingService.get_status()
    gumroad_status = GumroadService.get_status()

    yt_safe = {k: v for k, v in yt_status.items() if "token" not in k.lower() and "secret" not in k.lower()}
    ig_safe = {k: v for k, v in ig_status.items() if "token" not in k.lower() and "secret" not in k.lower()}
    gumroad_safe = {k: v for k, v in gumroad_status.items() if "token" not in k.lower() and "secret" not in k.lower()}

    base_context = {
        "integrations": {
            "youtube": yt_safe,
            "instagram": ig_safe,
            "gumroad": gumroad_safe,
            "ai_text": ai_status,
            "ai_image": ai_image_status,
            "media_hosting": media_hosting,
        },
        "venture_assets": {
            "digital_products_count": prod_cnt,
            "recent_products": recent_prods,
            "affiliate_offers_count": aff_cnt,
            "affiliate_clicks": aff_clicks,
            "affiliate_conversions": aff_convs,
            "affiliate_earned": aff_earned,
            "image_assets_count": image_cnt,
            "recent_images": recent_images,
            "instagram_posts_count": ig_post_cnt,
            "recent_instagram_posts": recent_ig_posts,
            "youtube_clips_count": clips_cnt,
            "youtube_schedule": schedule_cfg,
            "youtube_scheduled_posts_count": scheduled_posts_cnt,
            "completed_content_jobs_count": content_cnt,
        },
        "context_built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not exp_row:
        conn.close()
        base_context.update({
            "has_experiment": False,
            "summary": "No active experiments currently in SQLite. Use 'Launch Venture Run' on the dashboard to start.",
        })
        return base_context

    # ── If experiment exists, add experiment details ──────────────────────────
    exp = dict(exp_row)
    exp_id = exp["id"]

    # Selected opportunity
    cur.execute(
        "SELECT * FROM opportunities WHERE experiment_id = ? AND selected = 1 ORDER BY id DESC LIMIT 1",
        (exp_id,)
    )
    opp_row = cur.fetchone()
    opportunity = dict(opp_row) if opp_row else {}

    # Agent runs
    cur.execute(
        "SELECT agent_name, status, input_summary, output_summary, decision_reason, "
        "warning_or_error, updated_at FROM agent_runs WHERE experiment_id = ? ORDER BY id ASC",
        (exp_id,)
    )
    agent_runs = [dict(r) for r in cur.fetchall()]

    # Latest artifact
    cur.execute(
        "SELECT * FROM artifacts WHERE experiment_id = ? ORDER BY id DESC LIMIT 1",
        (exp_id,)
    )
    art_row = cur.fetchone()
    artifact = None
    if art_row:
        art = dict(art_row)
        meta = {}
        try:
            meta = json.loads(art.get("meta_json") or "{}")
        except Exception:
            pass
        import os
        artifact = {
            "title": art.get("title"),
            "hook": art.get("hook"),
            "call_to_action": art.get("call_to_action"),
            "video_available": bool(art.get("file_path") and os.path.exists(art["file_path"])),
            "video_path": art.get("file_path"),
            "image_available": bool(meta.get("image") and os.path.exists(meta["image"])),
            "deliverable_available": bool(meta.get("deliverable") and os.path.exists(meta["deliverable"])),
            "price": meta.get("price"),
        }

    # Finance
    cur.execute(
        "SELECT * FROM finance_records WHERE experiment_id = ? ORDER BY id DESC LIMIT 1",
        (exp_id,)
    )
    fin_row = cur.fetchone()
    finance = dict(fin_row) if fin_row else {}

    # Traffic
    cur.execute("SELECT COUNT(*) as cnt FROM traffic_events WHERE experiment_id = ? AND event_type='view'", (exp_id,))
    views = cur.fetchone()["cnt"] or 0
    cur.execute("SELECT COUNT(*) as cnt FROM traffic_events WHERE experiment_id = ? AND event_type='click'", (exp_id,))
    clicks = cur.fetchone()["cnt"] or 0

    # Orders (distinguishing real vs test)
    cur.execute("SELECT COUNT(*) as cnt, SUM(gross_amount) as gross FROM orders WHERE experiment_id = ? AND is_test = 0 AND is_refunded = 0", (exp_id,))
    real_stat = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) as cnt FROM orders WHERE experiment_id = ? AND is_test = 1", (exp_id,))
    test_stat = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) as cnt FROM orders WHERE experiment_id = ? AND is_refunded = 1", (exp_id,))
    refund_stat = dict(cur.fetchone())

    # Recent activity feed
    cur.execute(
        "SELECT agent_name, message, severity, timestamp FROM activity_feed "
        "WHERE experiment_id = ? ORDER BY id DESC LIMIT 10",
        (exp_id,)
    )
    recent_events = [dict(r) for r in cur.fetchall()]

    # Quality check
    cur.execute("SELECT passed, score, issues_json FROM quality_checks WHERE experiment_id = ? ORDER BY id DESC LIMIT 1", (exp_id,))
    qc_row = cur.fetchone()
    quality = None
    if qc_row:
        issues = []
        try:
            issues = json.loads(qc_row["issues_json"] or "[]")
        except Exception:
            pass
        quality = {"passed": bool(qc_row["passed"]), "score": qc_row["score"], "issues": issues}

    # Portfolio
    cur.execute("SELECT risk_profile, total_surplus, allocations_json FROM portfolio_allocations WHERE experiment_id = ? ORDER BY id DESC LIMIT 1", (exp_id,))
    port_row = cur.fetchone()
    portfolio = None
    if port_row:
        portfolio = {
            "risk_profile": port_row["risk_profile"],
            "total_surplus": port_row["total_surplus"],
        }

    conn.close()

    interrupted = exp.get("status") == "running" and any(r.get("status") == "running" for r in agent_runs)

    base_context.update({
        "has_experiment": True,
        "experiment": {
            "id": exp_id,
            "name": exp.get("name", ""),
            "goal": exp.get("goal", ""),
            "status": exp.get("status", "unknown"),
            "budget_limit": exp.get("budget_limit"),
            "budget_used": exp.get("budget_used"),
            "business_model": exp.get("business_model", ""),
            "target_audience": exp.get("target_audience", ""),
            "recommended_action": exp.get("recommended_action"),
            "created_at": exp.get("created_at"),
            "updated_at": exp.get("updated_at"),
            "interrupted": interrupted,
        },
        "selected_opportunity": {
            "title": opportunity.get("title", "Not yet selected"),
            "niche": opportunity.get("niche"),
            "business_model": opportunity.get("business_model"),
            "evidence": opportunity.get("evidence"),
            "confidence": opportunity.get("confidence", "unknown"),
            "source_type": opportunity.get("source_type"),
        } if opportunity else None,
        "agent_runs": agent_runs,
        "artifact": artifact,
        "finance": {
            "starting_budget": finance.get("starting_budget"),
            "actual_spend": finance.get("actual_spend"),
            "gross_revenue": finance.get("gross_revenue"),
            "fees": finance.get("fees"),
            "refunds": finance.get("refunds"),
            "net_profit": finance.get("net_profit"),
            "required_reserve": finance.get("required_reserve"),
            "reinvestment_allocated": finance.get("reinvestment_allocated"),
            "surplus_available": finance.get("surplus_available"),
            "is_simulated": bool(finance.get("is_simulated", 1)),
        } if finance else None,
        "traffic": {
            "views": views,
            "clicks": clicks,
            "ctr_pct": round(clicks / views * 100, 2) if views > 0 else 0.0,
            "data_quality": "sufficient" if views >= 25 else "insufficient_sample_size",
        },
        "orders": {
            "real_completed": real_stat.get("cnt") or 0,
            "real_gross": float(real_stat.get("gross") or 0.0),
            "test_orders": test_stat.get("cnt") or 0,
            "refunded": refund_stat.get("cnt") or 0,
        },
        "quality": quality,
        "portfolio": portfolio,
        "recent_events": recent_events,
    })

    return base_context

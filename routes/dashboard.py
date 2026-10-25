from flask import Blueprint, render_template, request, jsonify, send_file
import sqlite3
import json
from database import get_db_connection
from services.social_service import YouTubeService, InstagramService
from services.ai_service import AIService
from services.clipper_mcp_client import ClipperMCPClient
import config
from pathlib import Path

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/")
def index():
    return render_template("dashboard.html")


@dashboard_bp.route("/api/overview")
def api_overview():
    conn = get_db_connection()
    cur = conn.cursor()

    exp_id = request.args.get("experiment_id")
    if exp_id:
        cur.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,))
        exp_row = cur.fetchone()
    else:
        cur.execute(
            "SELECT * FROM experiments WHERE id IN "
            "(SELECT experiment_id FROM artifacts) ORDER BY id DESC LIMIT 1"
        )
        exp_row = cur.fetchone()
        if not exp_row:
            cur.execute("SELECT * FROM experiments ORDER BY id DESC LIMIT 1")
            exp_row = cur.fetchone()

    if not exp_row:
        conn.close()
        return jsonify({
            "has_data": False,
            "integrations": {
                "youtube": YouTubeService.get_status(),
                "instagram": InstagramService.get_status(),
                "ai": AIService.get_provider_status(),
                "openshorts": ClipperMCPClient.get_status(),
                "local_clipper": {"available": True, "engine": "faster-whisper + FFmpeg"}
            }
        })

    exp = dict(exp_row)
    exp_id = exp["id"]

    # Detect interrupted runs across server restarts
    from agents.orchestrator import RealMINTOrchestrator
    is_actively_running = exp_id in RealMINTOrchestrator._running_experiments
    if exp.get("status") == "running" and not is_actively_running:
        exp["status"] = "interrupted"
        cur.execute("UPDATE experiments SET status = 'interrupted' WHERE id = ? AND status = 'running'", (exp_id,))
        cur.execute("""
            UPDATE agent_runs 
            SET status = 'interrupted', warning_or_error = 'Execution interrupted by server restart.'
            WHERE experiment_id = ? AND status = 'running'
        """, (exp_id,))
        conn.commit()

    cur.execute("SELECT * FROM finance_records WHERE experiment_id = ? ORDER BY id DESC LIMIT 1", (exp_id,))
    fin_row = cur.fetchone()
    finance = dict(fin_row) if fin_row else None

    # Backfill budget_used for older experiments
    if exp.get("budget_used") is None and finance:
        exp["budget_used"] = finance.get("actual_spend", 0.0)

    cur.execute("SELECT * FROM portfolio_allocations WHERE experiment_id = ? ORDER BY id DESC LIMIT 1", (exp_id,))
    port_row = cur.fetchone()
    portfolio = None
    if port_row:
        portfolio = dict(port_row)
        portfolio["allocations"] = json.loads(portfolio["allocations_json"])

    cur.execute("SELECT * FROM artifacts WHERE experiment_id = ? ORDER BY id DESC LIMIT 1", (exp_id,))
    art_row = cur.fetchone()
    artifact = dict(art_row) if art_row else None
    if artifact:
        fp = artifact.get("file_path")
        artifact["file_exists"] = bool(fp and os.path.exists(fp))
        artifact["file_status"] = "ready" if artifact["file_exists"] else "missing_asset"

    cur.execute("SELECT * FROM quality_checks WHERE experiment_id = ? ORDER BY id DESC LIMIT 1", (exp_id,))
    qc_row = cur.fetchone()
    quality = None
    if qc_row:
        quality = dict(qc_row)
        quality["issues"] = json.loads(quality["issues_json"])

    cur.execute("SELECT * FROM agent_runs WHERE experiment_id = ? ORDER BY id ASC", (exp_id,))
    agent_runs = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM activity_feed WHERE experiment_id = ? ORDER BY id DESC LIMIT 20", (exp_id,))
    feed = [dict(r) for r in cur.fetchall()]

    # Real vs test orders
    cur.execute("SELECT COUNT(*) as cnt, SUM(gross_amount) as gross FROM orders WHERE experiment_id = ? AND is_test = 0", (exp_id,))
    real_stat = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) as cnt, SUM(gross_amount) as gross FROM orders WHERE experiment_id = ? AND is_test = 1", (exp_id,))
    test_stat = dict(cur.fetchone())

    cur.execute("SELECT COUNT(*) as cnt FROM traffic_events WHERE experiment_id = ? AND event_type = 'view'", (exp_id,))
    real_views = cur.fetchone()["cnt"] or 0
    cur.execute("SELECT COUNT(*) as cnt FROM traffic_events WHERE experiment_id = ? AND event_type = 'click'", (exp_id,))
    real_clicks = cur.fetchone()["cnt"] or 0

    conn.close()

    return jsonify({
        "has_data": True,
        "experiment": exp,
        "finance": finance,
        "portfolio": portfolio,
        "artifact": artifact,
        "quality": quality,
        "agent_runs": agent_runs,
        "activity_feed": feed,
        "traffic_summary": {
            "views": real_views,
            "clicks": real_clicks,
            "ctr_pct": round((real_clicks / real_views * 100.0), 2) if real_views > 0 else 0.0,
            "source": "verified_local_traffic_events" if real_views > 0 else "no_traffic_recorded_yet"
        },
        "orders_summary": {
            "real_orders_count": real_stat["cnt"] or 0,
            "real_gross": real_stat["gross"] or 0.0,
            "test_orders_count": test_stat["cnt"] or 0,
            "test_gross": test_stat["gross"] or 0.0
        },
        "integrations": {
            "youtube": YouTubeService.get_status(),
            "instagram": InstagramService.get_status(),
            "ai": AIService.get_provider_status(),
            "openshorts": ClipperMCPClient.get_status(),
            "local_clipper": {"available": True, "engine": "faster-whisper + FFmpeg"}
        }
    })


@dashboard_bp.route("/api/live-state")
def api_live_state():
    """
    Lightweight endpoint for the live agent visualization.
    Returns only agent run statuses, recent events, and experiment status.
    Does NOT repeat full finance/portfolio/artifact data (use /api/overview for that).
    Detects interrupted runs (status=running but server restarted).
    """
    conn = get_db_connection()
    cur = conn.cursor()

    exp_id = request.args.get("experiment_id")
    if exp_id:
        cur.execute("SELECT id, status, name, goal, updated_at FROM experiments WHERE id = ?", (exp_id,))
    else:
        cur.execute(
            "SELECT id, status, name, goal, updated_at FROM experiments "
            "ORDER BY id DESC LIMIT 1"
        )
    exp_row = cur.fetchone()

    if not exp_row:
        conn.close()
        return jsonify({"has_experiment": False, "agent_runs": [], "recent_events": []})

    exp = dict(exp_row)
    exp_id = exp["id"]

    cur.execute(
        "SELECT agent_name, status, input_summary, output_summary, "
        "decision_reason, warning_or_error, updated_at "
        "FROM agent_runs WHERE experiment_id = ? ORDER BY id ASC",
        (exp_id,)
    )
    agent_runs = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT agent_name, message, severity, timestamp "
        "FROM activity_feed WHERE experiment_id = ? ORDER BY id DESC LIMIT 15",
        (exp_id,)
    )
    recent_events = [dict(r) for r in cur.fetchall()]

    conn.close()

    # Detect interrupted runs: if experiment is marked 'running' but the server
    # has just restarted (no in-process experiment lock), mark agents as interrupted.
    from agents.orchestrator import RealMINTOrchestrator
    is_actually_running = exp_id in RealMINTOrchestrator._running_experiments

    if exp["status"] == "running" and not is_actually_running:
        exp["status"] = "interrupted"
        with get_db_connection() as conn_fix:
            conn_fix.execute("UPDATE experiments SET status = 'interrupted' WHERE id = ? AND status = 'running'", (exp_id,))
            conn_fix.execute("""
                UPDATE agent_runs 
                SET status = 'interrupted', warning_or_error = 'Execution interrupted by server restart.'
                WHERE experiment_id = ? AND status = 'running'
            """, (exp_id,))
            conn_fix.commit()
        for run in agent_runs:
            if run["status"] == "running":
                run["status"] = "interrupted"
                run["warning_or_error"] = (
                    run.get("warning_or_error") or
                    "Server restarted while this agent was running. Relaunch the experiment to continue."
                )

    # Compute live stage progression and elapsed time
    completed_cnt = sum(1 for r in agent_runs if r.get("status") == "completed")
    running_agent = next((r for r in agent_runs if r.get("status") == "running"), None)
    current_stage_name = running_agent["agent_name"] if running_agent else (
        "Pipeline Completed" if exp.get("status") == "completed" else (
            "Interrupted" if exp.get("status") == "interrupted" else "Initializing"
        )
    )
    current_task = running_agent.get("input_summary") or running_agent.get("output_summary") if running_agent else ""

    from datetime import datetime
    elapsed_sec = 0
    try:
        created_dt = datetime.strptime(exp.get("created_at") or exp.get("updated_at"), "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.now() if (exp.get("status") == "running" and is_actually_running) else datetime.strptime(exp.get("updated_at"), "%Y-%m-%d %H:%M:%S")
        elapsed_sec = max(0, int((end_dt - created_dt).total_seconds()))
    except Exception:
        elapsed_sec = 0

    progression = {
        "total_stages": 9,
        "completed_stages": completed_cnt,
        "progress_pct": min(100, int((completed_cnt / 9.0) * 100)),
        "current_stage": current_stage_name,
        "current_task": current_task,
        "elapsed_seconds": elapsed_sec,
        "is_actively_running": is_actually_running
    }

    return jsonify({
        "has_experiment": True,
        "experiment": exp,
        "agent_runs": agent_runs,
        "recent_events": recent_events,
        "is_actively_running": is_actually_running,
        "progression": progression
    })


ALLOWED_MEDIA_CATEGORIES = {"images", "videos", "products"}

@dashboard_bp.route("/api/media/<category>/<filename>")
def serve_media(category, filename):
    import os
    if category not in ALLOWED_MEDIA_CATEGORIES:
        return "Category not allowed", 400

    safe_filename = os.path.basename(filename)
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    folder = (gen_dir / category).resolve()
    file_path = (folder / safe_filename).resolve()

    # Prevent directory traversal
    try:
        if file_path.parent != folder or not file_path.is_file():
            return "File not found", 404
    except Exception:
        return "File not found", 404

    return send_file(str(file_path))


@dashboard_bp.route("/api/youtube/channel")
def youtube_channel_info():
    """Return cached channel info from YouTube API. Refreshes every 5 min."""
    force = request.args.get("refresh") == "1"
    info = YouTubeService.get_channel_info(force_refresh=force)
    upload_history = YouTubeService.get_upload_history()
    return jsonify({
        "channel": info,
        "upload_history": upload_history,
        "note": "Statistics (views, subscribers) are from the YouTube API. "
                "Upload history is MINT's own records of what it uploaded — "
                "it does not include YouTube analytics or revenue data.",
    })


@dashboard_bp.route("/api/instagram/status")
def instagram_status():
    """Return a safe Instagram diagnostic; refresh=1 or force_refresh=1 bypasses the status cache."""
    force_refresh = request.args.get("refresh") == "1" or request.args.get("force_refresh") == "1"
    status = InstagramService.get_status(force_refresh=force_refresh)
    return jsonify(status)


@dashboard_bp.route("/api/instagram/diagnostic")
def instagram_diagnostic():
    """Returns comprehensive 10-point diagnostic check of Instagram readiness."""
    return jsonify(InstagramService.get_detailed_diagnostics())


@dashboard_bp.route("/api/system/audit")
def system_audit():
    """Returns dry-run reference audit and consistency inventory across database and disk."""
    from services.cleanup_service import CleanupService
    return jsonify(CleanupService.get_inventory())

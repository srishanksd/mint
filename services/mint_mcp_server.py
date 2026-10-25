"""
services/mint_mcp_server.py
Official MCP Server for MINT Venture Control.
Exposes real application tools over Model Context Protocol using official Python MCP SDK.
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

from mcp.server.mcpserver import MCPServer
from database import get_db_connection

# Initialize the MINT MCPServer instance
mint_mcp_app = MCPServer("MINT-Venture-Control")


@mint_mcp_app.tool()
def get_dashboard_metrics() -> Dict[str, Any]:
    """
    Returns real-time venture metrics directly from SQLite database:
    active products, revenue, profit, clip counts, and integration health.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as cnt FROM digital_products")
    prod_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM youtube_clips")
    clips_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM image_assets")
    img_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT SUM(gross_amount) as total_rev FROM orders WHERE is_refunded = 0 AND is_test = 0")
    row = cur.fetchone()
    real_rev = float(row["total_rev"] or 0.0) if row else 0.0

    # Integration statuses
    from services.social_service import InstagramService
    from routes.youtube_auth import _load_token

    yt_token = _load_token("youtube")
    yt_connected = bool(yt_token and (getattr(yt_token, "refresh_token", None) or (isinstance(yt_token, dict) and yt_token.get("refresh_token"))))

    ig_status = InstagramService.get_status()

    conn.close()
    return {
        "success": True,
        "digital_products_count": prod_cnt,
        "youtube_clips_count": clips_cnt,
        "image_assets_count": img_cnt,
        "real_revenue_usd": real_rev,
        "youtube_connected": yt_connected,
        "instagram_connected": ig_status.get("status") == "connected",
        "instagram_status": ig_status.get("status"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


@mint_mcp_app.tool()
def check_instagram_readiness() -> Dict[str, Any]:
    """
    Runs diagnostic on Instagram authentication, Meta Graph API connectivity,
    token permissions, and HTTPS media hosting readiness.
    """
    from services.social_service import InstagramService
    return InstagramService.get_status(force_refresh=True)


@mint_mcp_app.tool()
def get_youtube_queue_and_schedule() -> Dict[str, Any]:
    """
    Retrieves YouTube clipping queue, schedule slots (Slot 1 & Slot 2),
    and clip statuses (ready, scheduled, published, failed).
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM youtube_schedule_config WHERE id = 1")
    sched_row = cur.fetchone()
    sched = dict(sched_row) if sched_row else {
        "enabled": 1,
        "slot_1_time": "10:00",
        "slot_2_time": "18:00",
        "timezone": "Asia/Kolkata",
        "auto_publish": 0
    }

    cur.execute("""
        SELECT id, clip_title, duration_sec, aspect_ratio, status,
               virality_score, provider, youtube_video_url, created_at
        FROM youtube_clips
        ORDER BY id DESC LIMIT 10
    """)
    clips = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "success": True,
        "schedule": sched,
        "recent_clips": clips,
        "total_clips": len(clips)
    }


@mint_mcp_app.tool()
def get_financial_summary() -> Dict[str, Any]:
    """
    Returns accounting metrics: gross revenue, expenses, net profit,
    25% mandatory reinvestment reserve lock, and available paper surplus.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT SUM(gross_amount) as total_rev FROM orders WHERE is_refunded = 0 AND is_test = 0")
    rev_row = cur.fetchone()
    gross_rev = float(rev_row["total_rev"] or 0.0) if rev_row else 0.0

    cur.execute("SELECT SUM(budget_used) as total_exp FROM experiments")
    exp_row = cur.fetchone()
    expenses = float(exp_row["total_exp"] or 0.0) if exp_row else 0.0

    net_profit = max(0.0, gross_rev - expenses)
    reserve = round(net_profit * 0.25, 2)
    surplus = round(net_profit - reserve, 2)

    conn.close()
    return {
        "success": True,
        "gross_revenue": gross_rev,
        "expenses": expenses,
        "net_profit": net_profit,
        "reserve_locked_25pct": reserve,
        "paper_surplus_available": surplus
    }


@mint_mcp_app.tool()
def list_active_experiments() -> Dict[str, Any]:
    """
    Lists recent venture experiments with business model, target audience,
    budget limit, budget used, and status.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, goal, business_model, target_audience,
               budget_limit, budget_used, status, created_at
        FROM experiments
        ORDER BY id DESC LIMIT 5
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "success": True,
        "experiments": rows,
        "count": len(rows)
    }


def run_stdio():
    """Runs the MCP server over stdio for external MCP clients."""
    asyncio.run(mint_mcp_app.run_stdio_async())


if __name__ == "__main__":
    run_stdio()

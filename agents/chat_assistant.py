"""
agents/chat_assistant.py
MINT Control Assistant — connected to real system state via context_builder.
Uses the actual database for all context; never invents metrics or completed tasks.
Maintains persistent conversation history across browser refreshes using conversation_id.
"""

import re
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from database import get_db_connection, log_activity
from services.ai_service import AIService
from agents.quality_agent import QualityCheckerAgent
from agents.context_builder import build_context


def _build_operational_answer(ctx: dict, text: str) -> str:
    """
    Deterministic operational answer generator based strictly on current SQLite records.
    Used when no external LLM is configured or as fallback.
    """
    lower = text.lower()
    integrations = ctx.get("integrations", {})
    yt = integrations.get("youtube", {})
    ig = integrations.get("instagram", {})
    gum = integrations.get("gumroad", {})
    ai_img = integrations.get("ai_image", {})
    media_host = integrations.get("media_hosting", {})

    assets = ctx.get("venture_assets", {})
    prods = assets.get("recent_products", [])
    prod_cnt = assets.get("digital_products_count", 0)
    aff_cnt = assets.get("affiliate_offers_count", 0)
    aff_clicks = assets.get("affiliate_clicks", 0)
    aff_earned = assets.get("affiliate_earned", 0.0)
    img_cnt = assets.get("image_assets_count", 0)
    yt_clips_cnt = assets.get("youtube_clips_count", 0)
    yt_sched = assets.get("youtube_schedule", {})

    # 1. Cloudflare Workers AI Image Generation inquiry
    if any(w in lower for w in ["image", "flux", "cloudflare", "photo", "picture"]):
        configured = ai_img.get("configured", False)
        model = ai_img.get("model", "@cf/black-forest-labs/flux-1-schnell")
        if configured:
            return (
                f"Image Generation is configured with Cloudflare Workers AI ({model}) on the free daily allocation "
                f"(10,000 neurons/day). Total generated image assets in database: {img_cnt}. "
                "You can generate standalone images in Mode B or create product marketing graphics in Mode A."
            )
        return (
            f"Cloudflare Workers AI image generation is not configured ({ai_img.get('message')}). "
            "To enable free image generation, configure CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in your .env file."
        )

    # 2. YouTube clipping and twice-daily schedule inquiry
    if any(w in lower for w in ["youtube", "clip", "schedule", "shorts"]):
        connected = yt.get("connected", False)
        ch_name = yt.get("channel_name") or "Authorized Channel"
        sched_enabled = bool(yt_sched.get("enabled", 0))
        slot1 = yt_sched.get("slot_1_time", "10:00")
        slot2 = yt_sched.get("slot_2_time", "18:00")
        tz = yt_sched.get("timezone", "UTC")
        timing_source = yt_sched.get("audience_timing_source", "user_configured_studio")

        if connected:
            sched_status = f"Active ({slot1} and {slot2} {tz}, source: {timing_source})" if sched_enabled else "Paused/Disabled"
            return (
                f"YouTube is connected as '{ch_name}'. Total clips rendered: {yt_clips_cnt}. "
                f"Twice-Daily Posting Schedule: {sched_status}. "
                "Clips are uploaded with status.publishAt set to future slots as private, becoming public automatically at the scheduled time."
            )
        return (
            "YouTube is not connected. Open the dashboard and click 'Connect YouTube' to complete "
            "the official Google OAuth 2.0 authorization flow. Clips can be cut from authorized source media."
        )

    # 3. Public Media Hosting inquiry
    if any(w in lower for w in ["media hosting", "hosting", "cloudinary", "cdn"]):
        if media_host.get("configured"):
            return f"Public HTTPS Media Hosting is ready via {media_host.get('provider_label')}. Meta Graph API can download your images for Instagram publishing."
        return (
            f"Public HTTPS Media Hosting is not configured ({media_host.get('message')}). "
            "Meta Graph API cannot access files from localhost. Configure Cloudinary credentials in .env to enable Instagram publishing."
        )

    # 4. Gumroad specific inquiry
    if "gumroad" in lower:
        if gum.get("connected"):
            user_info = gum.get("user", {})
            user_name = user_info.get("name") or user_info.get("email") or "Authorized User"
            prod_summary = []
            for p in prods[:3]:
                sync_st = p.get("gumroad_sync_status", "not_synced")
                att_st = p.get("gumroad_attachment_status", "missing")
                prod_summary.append(f"'{p.get('title')}' ({sync_st}, attachment: {att_st})")
            prods_text = "; ".join(prod_summary) if prod_summary else "No catalog products currently synced."
            return (
                f"Gumroad is connected as {user_name}. Auto-publish: {gum.get('auto_publish')}.\n"
                f"Recent products: {prods_text}.\n"
                f"Note: Local PDF deliverables must be manually attached via Gumroad Product Editor unless verified."
            )
        return (
            f"Gumroad is not connected ({gum.get('message', 'No access token')}). "
            "To connect Gumroad, add GUMROAD_ACCESS_TOKEN to your .env file."
        )

    # 5. Instagram specific inquiry
    if "instagram" in lower or "meta" in lower:
        status = ig.get("status", "not_configured")
        if status == "connected":
            return (
                f"Instagram is connected as @{ig.get('username')} ({ig.get('account_type')}). "
                "Publishing is enabled. Public HTTPS media hosting is required by Meta to retrieve images."
            )
        elif status == "not_configured":
            return (
                "Instagram is not configured. Missing INSTAGRAM_ACCOUNT_ID or INSTAGRAM_ACCESS_TOKEN in .env. "
                "Add your Page token with instagram_business_content_publish scope to enable publishing."
            )
        return f"Instagram status: {status} ({ig.get('message')})"

    # 6. Products & Affiliate catalog inquiry
    if any(w in lower for w in ["product", "affiliate", "catalog", "offer", "store"]):
        return (
            f"MINT currently has {prod_cnt} real digital products in the catalog and {aff_cnt} active affiliate offers. "
            f"Recorded affiliate traffic: {aff_clicks} clicks, verified commissions: ${aff_earned:.2f}. "
            "Products are generated using Chromium PDF rendering and synced with Gumroad."
        )

    # 7. If experiment is required for operational answer but missing
    if not ctx.get("has_experiment"):
        return (
            "No active experiments found in SQLite. "
            "Click 'Launch Venture Run' on the dashboard to start your first venture run. "
            f"System status: Products ({prod_cnt}), Images ({img_cnt}), Clips ({yt_clips_cnt}), "
            f"YouTube {'connected' if yt.get('connected') else 'disconnected'}, Instagram {ig.get('status', 'not configured')}."
        )

    exp = ctx.get("experiment", {})
    fin = ctx.get("finance") or {}
    traf = ctx.get("traffic") or {}
    orders = ctx.get("orders") or {}
    art = ctx.get("artifact") or {}
    opp = ctx.get("selected_opportunity") or {}
    runs = ctx.get("agent_runs", [])

    # Blocker / failure question
    if any(w in lower for w in ["fail", "error", "block", "problem", "wrong"]):
        failed_agents = [r for r in runs if r.get("status") in ("failed", "interrupted")]
        if failed_agents:
            details = "; ".join([f"{r['agent_name']}: {r.get('warning_or_error') or r.get('status')}" for r in failed_agents])
            return f"Current run has issues: {details}. Inspect the node in the pipeline."
        if exp.get("status") == "interrupted":
            return f"Experiment #{exp.get('id')} was interrupted while agents were running."
        return f"Current experiment #{exp.get('id')} has status '{exp.get('status')}'. No unhandled errors or blockers are currently flagged."

    # Next action / what now
    if any(w in lower for w in ["next", "now", "action", "do", "should"]):
        action = exp.get("recommended_action") or "Awaiting evaluation"
        traffic_views = traf.get("views", 0)
        advice = [f"System recommendation: {action}"]
        if traffic_views < 25:
            advice.append(f"Traffic sample size is low ({traffic_views} views). Generate additional promo posts in Content Studio to build signal.")
        if art.get("video_available") and yt.get("connected"):
            advice.append("Video artifact is rendered. Consider queueing a clip for YouTube Shorts.")
        if fin.get("surplus_available", 0) > 0:
            advice.append(f"Review paper portfolio surplus allocation (${fin.get('surplus_available'):.2f} available).")
        return "\n".join(advice)

    # Status / Progress summary
    budget_limit = exp.get("budget_limit", 0.0)
    budget_used = exp.get("budget_used", 0.0) or 0.0
    budget_pct = round((budget_used / budget_limit * 100), 1) if budget_limit > 0 else 0
    active_runs = [r["agent_name"] for r in runs if r.get("status") == "running"]
    completed_runs = len([r for r in runs if r.get("status") == "completed"])

    return (
        f"Experiment #{exp.get('id')} ('{exp.get('name')}') is currently {exp.get('status').upper()}. "
        f"Objective: '{exp.get('goal')}'.\n\n"
        f"• Strategy & Opportunity: Model is '{exp.get('business_model')}' targeting '{exp.get('target_audience')}'. "
        f"Selected concept: '{opp.get('title', 'Pending')}' (Confidence: {opp.get('confidence', 'unverified')}).\n"
        f"• Execution: {completed_runs}/9 agent steps completed. Budget cap: ${budget_limit:.2f} (used: ${budget_used:.2f}, {budget_pct}%).\n"
        f"• Deliverable: {art.get('title', 'Not yet rendered')} ({'Video Ready' if art.get('video_available') else 'No video'}).\n"
        f"• Performance & Traffic: {traf.get('views', 0)} verified views, {traf.get('clicks', 0)} clicks ({traf.get('ctr_pct', 0.0)}% CTR, {traf.get('data_quality')}). "
        f"Orders: {orders.get('real_completed', 0)} real (${orders.get('real_gross', 0.0):.2f}) and {orders.get('test_orders', 0)} sandbox orders.\n"
        f"• Accounting: Net profit ${fin.get('net_profit', 0.0):.2f}, 25% reserve locked: ${fin.get('required_reserve', 0.0):.2f}, paper surplus: ${fin.get('surplus_available', 0.0):.2f}.\n"
        f"• Integrations: YouTube {'connected' if yt.get('connected') else 'not connected'}; Instagram {ig.get('status', 'not configured')}."
    )


class RealChatAssistant:
    """
    Control Assistant for MINT.
    Executes real database state changes when operator issues clear commands,
    provides context-grounded strategic answers, and persists bounded conversation history.
    """

    def handle_message(self, experiment_id: Optional[int], user_text: str, conversation_id: str = "default") -> dict:
        text = user_text.strip()
        lower = text.lower()
        conv_id = (conversation_id or "default").strip()

        # ── Build focused real-time context ───────────────────────────────────
        ctx = build_context(experiment_id)

        conn = get_db_connection()
        cur = conn.cursor()

        # Resolve experiment id from context (handles None input)
        if ctx.get("has_experiment"):
            experiment_id = ctx["experiment"]["id"]
            exp = ctx["experiment"]
            art = ctx.get("artifact") or {}
        else:
            exp = {}
            art = {}

        # ── Load recent chat history for this conversation ────────────────────
        cur.execute(
            "SELECT sender, message FROM chat_messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT 10",
            (conv_id,)
        )
        history_rows = cur.fetchall()

        messages = []
        for r in reversed(history_rows):
            messages.append({
                "role": "user" if r["sender"] == "user" else "assistant",
                "content": r["message"]
            })
        messages.append({"role": "user", "content": text})

        # ── Call AI with real operational context ─────────────────────────────
        ai_res = AIService.generate_chat(messages, context=ctx)
        reply = ai_res.get("reply", "")
        action_taken = "No backend state modified."
        intent = "conversational_consultation"

        # ── Intent Detection & Action Execution ───────────────────────────────
        if ctx.get("has_experiment") and experiment_id:

            # 1. Stop Run
            if "stop" in lower and any(w in lower for w in ["run", "experiment", "pipeline", "workflow"]):
                intent = "control_stop"
                cur.execute(
                    "UPDATE experiments SET status = 'stopped', updated_at = ? WHERE id = ?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), experiment_id)
                )
                conn.commit()
                action_taken = "Experiment status set to STOPPED."
                log_activity(experiment_id, "MINT Orchestrator", "Active run stopped by operator via Control Assistant.", "warning")
                reply += "\n\n[Action Executed: Experiment stopped.]"

            # 2. Revise Hook (Fixed sqlite3.Row access via dict conversion)
            elif any(w in lower for w in ["hook", "headline"]) and any(w in lower for w in ["change", "make", "rewrite", "update", "clearer", "punchier", "set"]):
                intent = "revise_hook"
                matches = re.findall(r"[\"'](.*?)[\"']", text)
                if matches:
                    new_hook = matches[0]
                elif "REVISE_HOOK:" in reply:
                    new_hook = reply.split("REVISE_HOOK:")[1].split("\n")[0].strip()
                else:
                    new_hook = text

                cur.execute(
                    "SELECT id, call_to_action, disclaimer FROM artifacts WHERE experiment_id = ? ORDER BY id DESC LIMIT 1",
                    (experiment_id,)
                )
                art_row = cur.fetchone()
                if art_row:
                    art_dict = dict(art_row)
                    art_id = art_dict["id"]
                    cur.execute("UPDATE artifacts SET hook = ? WHERE id = ?", (new_hook, art_id))
                    conn.commit()
                    qc = QualityCheckerAgent()
                    q_res = qc.check_artifact(
                        new_hook,
                        art_dict.get("call_to_action", "Download"),
                        exp.get("business_model", "digital_product"),
                        art_dict.get("disclaimer", "")
                    )
                    cur.execute(
                        "INSERT INTO quality_checks (experiment_id, artifact_id, passed, score, issues_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (experiment_id, art_id, 1 if q_res["passed"] else 0, q_res["score"],
                         json.dumps(q_res["issues"]), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    )
                    conn.commit()
                    action_taken = f"Hook updated on artifact #{art_id}. Quality re-verified (score: {q_res['score']}/100)."
                    log_activity(experiment_id, "Content Creator", f"Hook revised to: '{new_hook}'.", "info")
                    reply += f"\n\n[Action Executed: Hook updated. Quality Score: {q_res['score']}/100]"
                else:
                    action_taken = "No artifact found to update hook on."
                    reply += "\n\n[Action Blocked: No generated artifact exists yet. Run an experiment first.]"

            # 3. Budget Revision
            elif any(w in lower for w in ["budget", "spending"]) and any(w in lower for w in ["reduce", "lower", "set", "change", "increase", "adjust"]):
                intent = "revise_budget"
                nums = re.findall(r"\$?([0-9]+(?:\.[0-9]+)?)", text)
                if nums:
                    new_budget = float(nums[0])
                    if 5.0 <= new_budget <= 5000.0:
                        cur.execute(
                            "UPDATE experiments SET budget_limit = ?, updated_at = ? WHERE id = ?",
                            (new_budget, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), experiment_id)
                        )
                        conn.commit()
                        action_taken = f"Budget adjusted to ${new_budget:.2f}."
                        log_activity(experiment_id, "MINT Orchestrator", f"Budget limit updated to ${new_budget:.2f}.", "info")
                        reply += f"\n\n[Action Executed: Budget cap updated to ${new_budget:.2f}]"
                    else:
                        action_taken = f"Budget ${new_budget:.2f} rejected — outside safety limits ($5–$5,000)."
                        reply += f"\n\n[Action Blocked: ${new_budget:.2f} is outside safety limits ($5.00–$5,000.00).]"
                else:
                    action_taken = "No budget amount found in message."

            # 4. Target Audience Revision
            elif any(w in lower for w in ["audience", "target"]) and any(w in lower for w in ["change", "update", "set", "switch", "target"]):
                intent = "revise_audience"
                matches = re.findall(r"(?:to|for|target)\s+([A-Za-z0-9\s,\-\+&]+)", text, re.IGNORECASE)
                new_aud = matches[0].strip() if matches else "Technical solopreneurs and indie software developers"
                cur.execute(
                    "UPDATE experiments SET target_audience = ?, updated_at = ? WHERE id = ?",
                    (new_aud, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), experiment_id)
                )
                conn.commit()
                action_taken = f"Target audience updated to '{new_aud}'."
                log_activity(experiment_id, "Strategy Agent", f"Target audience updated to: '{new_aud}'.", "info")
                reply += f"\n\n[Action Executed: Target audience set to: \"{new_aud}\"]"

            # 5. Fallback operational inquiry when AI provider is unconfigured
            elif ai_res.get("provider") == "none" or not reply:
                reply = _build_operational_answer(ctx, text)

        elif not ctx.get("has_experiment"):
            if any(k in lower for k in ["gumroad", "instagram", "youtube", "status", "integration", "connect", "image", "flux", "cloudflare", "clip", "schedule", "product", "affiliate"]):
                reply = _build_operational_answer(ctx, text)
            elif not reply or ai_res.get("provider") == "none" or not ai_res.get("success", True):
                reply = (
                    "No experiments have been launched yet. "
                    "Click 'Launch Venture Run' on the dashboard to start your first venture run. "
                    "I can also tell you about your digital products, Cloudflare Workers AI image setup, "
                    "YouTube clipping & scheduling, and Instagram connections."
                )

        # ── Record conversation reliably (even before first experiment exists) ──
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "INSERT INTO chat_messages (experiment_id, conversation_id, sender, message, intent_detected, action_taken, timestamp) "
            "VALUES (?, ?, 'user', ?, ?, ?, ?)",
            (experiment_id, conv_id, text, intent, action_taken, now)
        )
        cur.execute(
            "INSERT INTO chat_messages (experiment_id, conversation_id, sender, message, intent_detected, action_taken, timestamp) "
            "VALUES (?, ?, 'mint', ?, ?, ?, ?)",
            (experiment_id, conv_id, reply, intent, action_taken, now)
        )
        conn.commit()
        conn.close()

        return {
            "reply": reply,
            "intent": intent,
            "action_taken": action_taken,
            "provider_used": ai_res.get("provider", "local_deterministic_state"),
            "context_experiment_id": experiment_id,
            "conversation_id": conv_id,
        }

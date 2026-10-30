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
from services.mcp_agent_client import MCPAgentClient
from agents.quality_agent import QualityCheckerAgent
from agents.context_builder import build_context
from services.chroma_service import query_activities, get_recent_activities


def _build_operational_answer(ctx: dict, text: str) -> str:
    """
    Intelligent operational answer generator based on live SQLite records + ChromaDB semantic memory.
    Answers real questions directly without generic filler or random replies.
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
    img_cnt = assets.get("image_assets_count", 0)
    yt_clips_cnt = assets.get("youtube_clips_count", 0)
    yt_sched = assets.get("youtube_schedule", {})

    # Check ChromaDB memory first for relevant context
    chroma_matches = query_activities(text, n_results=3)
    memory_context = ""
    if chroma_matches:
        mem_snippets = [f"- {m['document']}" for m in chroma_matches[:3]]
        memory_context = "\nRelevant System Memory (ChromaDB):\n" + "\n".join(mem_snippets)

    # 1. Video clipping / YouTube inquiries
    if any(w in lower for w in ["clip", "video", "youtube", "shorts", "render"]):
        conn = get_db_connection()
        clips = [dict(r) for r in conn.execute("SELECT clip_title, status, duration_sec, output_path, youtube_video_url, created_at FROM youtube_clips ORDER BY id DESC LIMIT 5").fetchall()]
        conn.close()
        
        reply_lines = [f"YouTube Clips System (Native Faster-Whisper + 9:16 Zoom-Crop Renderer):"]
        reply_lines.append(f"• Total clips cataloged: {yt_clips_cnt}")
        reply_lines.append(f"• YouTube connection: {'Connected (' + str(yt.get('channel_name') or 'Channel') + ')' if yt.get('connected') else 'OAuth not connected'}")
        if clips:
            reply_lines.append("\nRecent Clips Generated:")
            for c in clips[:4]:
                link_str = f" [Watch: {c['youtube_video_url']}]" if c.get('youtube_video_url') else " [Local File]"
                reply_lines.append(f"• \"{c.get('clip_title')}\" ({c.get('status')}, {c.get('duration_sec', 0)}s){link_str}")
        return "\n".join(reply_lines)

    # 2. Digital Products inquiries
    if any(w in lower for w in ["product", "catalog", "guide", "ebook", "template", "deliverable"]):
        conn = get_db_connection()
        products = [dict(r) for r in conn.execute("SELECT title, price, product_type, audience, status FROM digital_products ORDER BY id DESC LIMIT 5").fetchall()]
        conn.close()

        lines = [f"Digital Products Catalog:"]
        lines.append(f"• Total products created: {prod_cnt}")
        if products:
            lines.append("Recent products:")
            for p in products:
                lines.append(f"• \"{p.get('title')}\" (${p.get('price', 0):.2f}, {p.get('product_type')}, Status: {p.get('status')})")
        return "\n".join(lines)

    # 3. Revenue, profit, orders, financial metrics
    if any(w in lower for w in ["money", "revenue", "profit", "order", "sales", "gross", "financial", "cash"]):
        fin = ctx.get("finance") or {}
        orders = ctx.get("orders") or {}
        gross = float(fin.get("gross_revenue", 0.0) or orders.get("real_gross", 0.0))
        net = float(fin.get("net_profit", 0.0))
        res = float(fin.get("required_reserve", 0.0))
        return (
            f"Financial Accounting Summary:\n"
            f"• Real Customer Revenue: ${gross:.2f}\n"
            f"• Net Operating Profit: ${net:.2f}\n"
            f"• Compulsory 25% Reserve: ${res:.2f}\n"
            f"• Orders: {orders.get('real_completed', 0)} real customer transactions."
        )

    # 4. Activity history / what happened / memory search
    if any(w in lower for w in ["activity", "history", "what happened", "recent", "log", "chroma", "memory"]):
        recent = get_recent_activities(limit=5)
        if recent:
            items_str = "\n".join([f"• [{r.get('timestamp')}] {r.get('document')}" for r in recent])
            return f"Most Recent Important System Activities (Indexed in ChromaDB):\n{items_str}"
        return "No activities recorded in memory yet."

    # 5. Instagram inquiries
    if "instagram" in lower or "meta" in lower:
        status = ig.get("status", "not_configured")
        if status == "connected":
            return f"Instagram Meta Graph is connected as @{ig.get('username')} ({ig.get('account_type')}). Publishing is ready."
        return f"Instagram status: {status} ({ig.get('message', 'Unconfigured')}). Local video files require a public HTTPS media hosting URL."

    # If query matches ChromaDB memory well, return memory answer
    if chroma_matches:
        top_doc = chroma_matches[0]["document"]
        return f"According to your system records:\n{top_doc}\n{memory_context}"

    # General overview
    return (
        f"MINT Personal Control Assistant ready.\n"
        f"• Clips: {yt_clips_cnt} created (Faster-Whisper & 9:16 renderer ready)\n"
        f"• Products: {prod_cnt} available in catalog\n"
        f"• YouTube: {'Connected' if yt.get('connected') else 'Disconnected'}\n"
        f"• ChromaDB Memory: Active & indexing all actions\n"
        f"Ask me about any video clip, product, past activity, or platform integration."
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
        if not ai_res.get("success") or "API Error" in reply or "quota" in reply.lower():
            operational = _build_operational_answer(ctx, text)
            if operational:
                reply = operational
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

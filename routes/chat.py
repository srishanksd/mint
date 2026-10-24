import logging
from flask import Blueprint, request, jsonify, current_app
from agents.chat_assistant import RealChatAssistant
from services.ai_service import AIService
from database import get_db_connection

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)
assistant = RealChatAssistant()


@chat_bp.route("/api/chat/status")
def chat_status():
    return jsonify(AIService.get_provider_status())


@chat_bp.route("/api/chat", methods=["POST"])
@chat_bp.route("/api/chat/send", methods=["POST"])
def send_chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    if not message:
        return jsonify({"error": "message is required and cannot be blank"}), 400

    conv_id = str(data.get("conversation_id", "default")).strip() or "default"

    exp_id = data.get("experiment_id")
    if exp_id not in (None, ""):
        try:
            exp_id = int(exp_id)
        except (TypeError, ValueError):
            return jsonify({"error": "experiment_id must be an integer"}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if exp_id is not None:
            cur.execute("SELECT id FROM experiments WHERE id = ?", (exp_id,))
            if not cur.fetchone():
                return jsonify({"error": f"Experiment #{exp_id} not found"}), 404
        else:
            cur.execute("SELECT id FROM experiments ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            exp_id = row["id"] if row else None
    finally:
        conn.close()

    try:
        # Pass conversation_id for persistent multi-turn conversational history
        result = assistant.handle_message(exp_id, message, conversation_id=conv_id)
        return jsonify(result)
    except Exception:
        logger.exception("Control Assistant request failed")
        return jsonify({
            "error": "Control Assistant could not process this message. Check the server log and try again."
        }), 500


@chat_bp.route("/api/chat/history")
def chat_history():
    """
    Returns messages in chronological order.
    Prefers conversation_id if provided; falls back to experiment_id or recent general messages.
    """
    conv_id = request.args.get("conversation_id")
    exp_id = request.args.get("experiment_id")

    conn = get_db_connection()
    cur = conn.cursor()

    if conv_id:
        cur.execute(
            "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC LIMIT 100",
            (conv_id,)
        )
    elif exp_id:
        cur.execute(
            "SELECT * FROM chat_messages WHERE experiment_id = ? ORDER BY id ASC LIMIT 100",
            (exp_id,)
        )
    else:
        cur.execute("SELECT * FROM chat_messages ORDER BY id ASC LIMIT 50")

    messages = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"messages": messages, "conversation_id": conv_id or "default"})

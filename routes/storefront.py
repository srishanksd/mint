import os
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, timedelta
import hashlib
from database import get_db_connection, log_activity

storefront_bp = Blueprint("storefront", __name__)

@storefront_bp.route("/storefront")
def store_view():
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch published/ready digital products and active partner offers
    cur.execute("SELECT * FROM digital_products WHERE status in ('published', 'ready') AND is_test = 0 ORDER BY id DESC")
    all_prods = [dict(r) for r in cur.fetchall()]

    # Filter to products with verified physical deliverables on disk
    valid_products = []
    for p in all_prods:
        fp = p.get("file_path") or p.get("pdf_path")
        pdf_p = p.get("pdf_path")
        if (fp and Path(fp).exists()) or (pdf_p and Path(pdf_p).exists()):
            p["has_pdf"] = bool(pdf_p and Path(pdf_p).exists())
            valid_products.append(p)

    cur.execute("SELECT * FROM affiliate_offers WHERE status = 'active' AND is_test = 0 ORDER BY id DESC")
    offers = [dict(r) for r in cur.fetchall()]

    # Fetch latest approved artifact for experiment view if available
    cur.execute("""
        SELECT a.* FROM artifacts a
        JOIN experiments e ON a.experiment_id = e.id
        WHERE e.status != 'failed'
        ORDER BY a.id DESC LIMIT 1
    """)
    art = cur.fetchone()

    # Log an authentic page view event with basic de-duplication (1 view per IP per 5 minutes)
    if art:
        exp_id = art["experiment_id"]
        ip = request.remote_addr or "127.0.0.1"
        ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:12]
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Check recent view from same IP within the 5-minute (300-second) deduplication window
        cur.execute("""
            SELECT id, created_at FROM traffic_events
            WHERE experiment_id = ? AND event_type = 'view' AND ip_hash = ?
            ORDER BY id DESC LIMIT 1
        """, (exp_id, ip_hash))
        recent_view = cur.fetchone()

        should_record = True
        if recent_view:
            try:
                prev_time = datetime.strptime(recent_view["created_at"], "%Y-%m-%d %H:%M:%S")
                if (now_dt - prev_time).total_seconds() < 300:
                    should_record = False
            except Exception:
                pass

        if should_record:
            cur.execute("""
                INSERT INTO traffic_events (experiment_id, event_type, source, referrer, ip_hash, created_at)
                VALUES (?, 'view', 'storefront', ?, ?, ?)
            """, (exp_id, request.referrer or "direct", ip_hash, now_str))
            conn.commit()

    conn.close()
    return render_template(
        "storefront.html",
        artifact=dict(art) if art else None,
        products=valid_products,
        offers=offers
    )

@storefront_bp.route("/api/storefront/log_click", methods=["POST"])
def log_click_event():
    data = request.get_json(silent=True) or {}
    exp_id = data.get("experiment_id")
    if not exp_id:
        return jsonify({"error": "experiment_id required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM experiments WHERE id = ?", (exp_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": f"Experiment #{exp_id} not found"}), 404

    ip = request.remote_addr or "127.0.0.1"
    ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:12]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO traffic_events (experiment_id, event_type, source, referrer, ip_hash, created_at)
        VALUES (?, 'click', 'storefront_checkout_cta', ?, ?, ?)
    """, (exp_id, request.referrer or "direct", ip_hash, now))
    conn.commit()
    conn.close()

    return jsonify({"status": "logged", "event": "click"})

@storefront_bp.route("/api/storefront/test_order", methods=["POST"])
def place_test_order():
    data = request.get_json(silent=True) or {}
    exp_id = data.get("experiment_id")
    if not exp_id:
        return jsonify({"error": "experiment_id is required"}), 400

    try:
        gross = float(data.get("price", 14.99))
    except (ValueError, TypeError):
        return jsonify({"error": "price must be a valid number"}), 400

    if gross <= 0.0 or gross > 5000.0:
        return jsonify({"error": "price must be between $0.01 and $5,000.00"}), 400

    email = str(data.get("email", "tester@mint-sandbox.local")).strip()[:100]
    fee = round(gross * 0.03 + 0.30, 2)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM experiments WHERE id = ?", (exp_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": f"Experiment #{exp_id} not found"}), 404

    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Anti-duplication check: avoid double clicking checkout within 15 seconds for same email & experiment
    cur.execute("""
        SELECT id, created_at FROM orders
        WHERE experiment_id = ? AND customer_email = ? AND is_refunded = 0
        ORDER BY id DESC LIMIT 1
    """, (exp_id, email))
    recent_order = cur.fetchone()
    if recent_order:
        try:
            prev_time = datetime.strptime(recent_order["created_at"], "%Y-%m-%d %H:%M:%S")
            if (now_dt - prev_time).total_seconds() < 15:
                conn.close()
                return jsonify({
                    "status": "duplicate_throttled",
                    "order_id": recent_order["id"],
                    "is_test": True,
                    "message": "Duplicate purchase request within cooldown period was suppressed."
                }), 200
        except Exception:
            pass

    cur.execute("""
        INSERT INTO orders (experiment_id, customer_email, product_title, gross_amount, fee_amount, is_refunded, refund_amount, is_test, created_at)
        VALUES (?, ?, 'Product Access License', ?, ?, 0, 0.0, 1, ?)
    """, (exp_id, email, gross, fee, now))
    conn.commit()
    order_id = cur.lastrowid
    conn.close()

    log_activity(exp_id, "Publishing and Commerce", f"Sandbox test purchase recorded (#{order_id}) for ${gross:.2f}.", "info")
    return jsonify({"status": "success", "order_id": order_id, "is_test": True})

@storefront_bp.route("/api/storefront/test_refund", methods=["POST"])
def refund_test_order():
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": "order_id is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    order = cur.fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "Order not found"}), 404

    if order["is_refunded"]:
        conn.close()
        return jsonify({"status": "already_refunded", "message": "Order is already marked as refunded."}), 200

    cur.execute("UPDATE orders SET is_refunded = 1, refund_amount = gross_amount WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

    log_activity(order["experiment_id"], "Finance Agent", f"Simulated refund processed for order #{order_id} (${order['gross_amount']:.2f}).", "warning")
    return jsonify({"status": "success", "refunded": True})

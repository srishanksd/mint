import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, abort
from database import get_db_connection

affiliates_bp = Blueprint("affiliates", __name__)

SALT = "MINT_PRIVACY_SALT_SECURE_HASH"

@affiliates_bp.route("/affiliates")
def affiliates_view():
    show_all = request.args.get("show_all") == "1" or request.args.get("admin") == "1"
    conn = get_db_connection()
    cur = conn.cursor()
    if show_all:
        cur.execute("SELECT * FROM affiliate_offers ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM affiliate_offers WHERE status = 'active' AND is_test = 0 ORDER BY id DESC")
    offers = [dict(r) for r in cur.fetchall()]

    for off in offers:
        cur.execute("SELECT COUNT(*) as clicks FROM affiliate_clicks WHERE offer_id = ?", (off["id"],))
        off["clicks"] = cur.fetchone()["clicks"]
        cur.execute("SELECT COUNT(*) as convs, SUM(commission_earned) as earned FROM affiliate_conversions WHERE offer_id = ?", (off["id"],))
        conv_row = cur.fetchone()
        off["conversions"] = conv_row["convs"] or 0
        off["commission_earned"] = conv_row["earned"] or 0.0

    # Fetch MINT / Gumroad Own Products (strictly segregated from affiliate offers)
    cur.execute("SELECT * FROM digital_products WHERE status != 'archived' AND is_test = 0 ORDER BY id DESC")
    own_prods_raw = [dict(r) for r in cur.fetchall()]
    own_products = []
    for p in own_prods_raw:
        fp = p.get("file_path") or p.get("pdf_path")
        pdf_p = p.get("pdf_path")
        p["has_deliverable"] = bool(fp and Path(fp).exists())
        p["has_pdf"] = bool(pdf_p and Path(pdf_p).exists())
        own_products.append(p)

    conn.close()
    return render_template("affiliates.html", offers=offers, own_products=own_products, show_all=show_all)

@affiliates_bp.route("/api/affiliate/offers", methods=["GET"])
def api_list_offers():
    status_filter = request.args.get("status")
    include_test = request.args.get("include_test") == "1"
    conn = get_db_connection()
    cur = conn.cursor()

    conditions = []
    params = []
    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)
    if not include_test:
        conditions.append("is_test = 0")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cur.execute(f"SELECT * FROM affiliate_offers {where_clause} ORDER BY id DESC", params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"offers": rows, "count": len(rows)})

@affiliates_bp.route("/api/affiliate/own_products", methods=["GET"])
def api_list_own_products():
    """
    Returns verified MINT/Gumroad digital products eligible for promotion.
    Segregated from third-party affiliate offers.
    """
    include_test = request.args.get("include_test") == "1"
    conn = get_db_connection()
    cur = conn.cursor()
    test_clause = "" if include_test else "AND is_test = 0"
    cur.execute(f"SELECT * FROM digital_products WHERE status != 'archived' {test_clause} ORDER BY id DESC")
    prods = [dict(r) for r in cur.fetchall()]
    conn.close()

    result = []
    for p in prods:
        fp = p.get("file_path") or p.get("pdf_path")
        pdf_p = p.get("pdf_path")
        p["has_deliverable"] = bool(fp and Path(fp).exists())
        p["has_pdf"] = bool(pdf_p and Path(pdf_p).exists())
        p["product_category"] = "own_product"
        result.append(p)

    return jsonify({"own_products": result, "count": len(result)})

@affiliates_bp.route("/api/affiliate/offers", methods=["POST"])
def api_create_offer():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    destination_url = str(data.get("destination_url", "")).strip()
    vendor = str(data.get("vendor", "")).strip() or "Independent Merchant"
    niche = str(data.get("niche", "Productivity")).strip()
    audience = str(data.get("audience", "Creators & Solopreneurs")).strip()
    description = str(data.get("description", "")).strip() or f"Specialized partner offer for {name}"
    commission_rate = str(data.get("commission_rate", "30%")).strip()
    price = float(data.get("price", 0.0))
    notes = str(data.get("notes", "")).strip()
    is_test = int(data.get("is_test", 0))
    disclosure_copy = str(data.get("disclosure_copy", "")).strip() or (
        "Transparency Disclosure: We may earn an affiliate commission if you purchase through this link at no additional charge to you."
    )

    if not name or not destination_url:
        return jsonify({"error": "name and destination_url are required"}), 400

    if not (destination_url.startswith("http://") or destination_url.startswith("https://")):
        return jsonify({"error": "destination_url must start with http:// or https://"}), 400

    token = "afr_" + uuid.uuid4().hex[:10]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO affiliate_offers (
            token, name, vendor, niche, audience, description, destination_url,
            commission_rate, price, notes, disclosure_copy, status, is_test, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
    """, (token, name, vendor, niche, audience, description, destination_url, commission_rate, price, notes, disclosure_copy, is_test, now, now))
    offer_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "offer_id": offer_id,
        "token": token,
        "redirect_path": f"/go/{token}"
    }), 201

@affiliates_bp.route("/api/affiliate/offers/<int:offer_id>", methods=["PUT"])
def api_update_offer(offer_id):
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM affiliate_offers WHERE id = ?", (offer_id,))
    off = cur.fetchone()
    if not off:
        conn.close()
        return jsonify({"error": f"Offer #{offer_id} not found"}), 404

    name = str(data.get("name", off["name"])).strip()
    vendor = str(data.get("vendor", off["vendor"])).strip()
    destination_url = str(data.get("destination_url", off["destination_url"])).strip()
    commission_rate = str(data.get("commission_rate", off["commission_rate"])).strip()
    niche = str(data.get("niche", off["niche"])).strip()
    audience = str(data.get("audience", off["audience"])).strip()
    description = str(data.get("description", off["description"])).strip()
    disclosure_copy = str(data.get("disclosure_copy", off["disclosure_copy"])).strip()
    status = str(data.get("status", off["status"])).strip().lower()

    if status not in ("active", "paused", "archived"):
        status = off["status"]

    if not destination_url.startswith("http://") and not destination_url.startswith("https://"):
        conn.close()
        return jsonify({"error": "destination_url must start with http:// or https://"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        UPDATE affiliate_offers
        SET name = ?, vendor = ?, destination_url = ?, commission_rate = ?,
            niche = ?, audience = ?, description = ?, disclosure_copy = ?,
            status = ?, updated_at = ?
        WHERE id = ?
    """, (name, vendor, destination_url, commission_rate, niche, audience, description, disclosure_copy, status, now, offer_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "offer_id": offer_id, "status": status})

@affiliates_bp.route("/api/affiliate/offers/<int:offer_id>/archive", methods=["POST"])
def api_archive_offer(offer_id):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE affiliate_offers SET status = 'archived', updated_at = ? WHERE id = ?", (now, offer_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "offer_id": offer_id, "status": "archived"})

@affiliates_bp.route("/api/affiliate/stats", methods=["GET"])
def api_affiliate_stats():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as total_offers FROM affiliate_offers WHERE status = 'active' AND is_test = 0")
    total_offers = cur.fetchone()["total_offers"] or 0

    cur.execute("SELECT COUNT(*) as total_clicks FROM affiliate_clicks WHERE is_test = 0")
    total_clicks = cur.fetchone()["total_clicks"] or 0

    cur.execute("""
        SELECT COUNT(*) as total_conversions, SUM(commission_earned) as total_earned
        FROM affiliate_conversions WHERE is_test = 0
    """)
    conv_data = cur.fetchone()
    total_convs = conv_data["total_conversions"] or 0
    total_earned = round(conv_data["total_earned"] or 0.0, 2)

    conn.close()

    return jsonify({
        "total_active_offers": total_offers,
        "total_clicks": total_clicks,
        "total_conversions": total_convs,
        "total_commission_earned": total_earned,
        "data_status": "real_tracked_events",
        "attribution_method": "sha256_hashed_visitor_id"
    })

@affiliates_bp.route("/api/affiliate/conversions", methods=["POST"])
def api_record_conversion():
    data = request.get_json(silent=True) or {}
    offer_id = data.get("offer_id")
    amount = float(data.get("amount", 0.0))
    commission_earned = float(data.get("commission_earned", 0.0))
    source_type = str(data.get("source_type", "manual_entry")).strip()
    evidence_ref = str(data.get("evidence_ref", "")).strip()

    if not offer_id or commission_earned <= 0:
        return jsonify({"error": "offer_id and positive commission_earned are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM affiliate_offers WHERE id = ?", (offer_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": f"Offer #{offer_id} not found"}), 404

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO affiliate_conversions (offer_id, amount, commission_earned, source_type, evidence_ref, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (offer_id, amount, commission_earned, source_type, evidence_ref, now))
    conv_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"success": True, "conversion_id": conv_id}), 201

@affiliates_bp.route("/go/<token>")
def outbound_safe_redirect(token):
    """
    Opaque, safe, privacy-preserving affiliate redirect.
    Strictly queries database by token; NEVER allows query parameter open redirects.
    Logs SHA-256 hashed visitor identity to prevent raw IP logging.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM affiliate_offers WHERE token = ? AND status = 'active'", (token,))
    offer = cur.fetchone()

    if not offer:
        conn.close()
        abort(404, description="Affiliate offer link not found or inactive.")

    dest = offer["destination_url"]

    # Privacy-conscious visitor hashing (IP + User-Agent + Salt)
    client_ip = request.remote_addr or "127.0.0.1"
    user_agent = request.headers.get("User-Agent", "unknown")
    raw_sig = f"{client_ip}_{user_agent}_{SALT}"
    visitor_hash = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_test = int(offer["is_test"]) if "is_test" in offer.keys() else 0

    cur.execute("""
        INSERT INTO affiliate_clicks (offer_id, source_page, visitor_hash, is_test, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (offer["id"], request.referrer or "direct", visitor_hash, is_test, now))
    conn.commit()
    conn.close()

    return redirect(dest, code=302)

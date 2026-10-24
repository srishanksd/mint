import json
from flask import Blueprint, render_template, jsonify
from database import get_db_connection

portfolio_bp = Blueprint("portfolio", __name__)

@portfolio_bp.route("/portfolio")
def portfolio_view():
    conn = get_db_connection()
    cur = conn.cursor()

    # Retrieve latest paper portfolio allocation
    cur.execute("SELECT * FROM portfolio_allocations ORDER BY id DESC LIMIT 1")
    alloc_row = cur.fetchone()
    paper_portfolio = None
    if alloc_row:
        paper_portfolio = dict(alloc_row)
        try:
            paper_portfolio["allocations"] = json.loads(paper_portfolio.get("allocations_json") or "[]")
        except Exception:
            paper_portfolio["allocations"] = []

    # Digital Products count & list
    cur.execute("SELECT * FROM digital_products ORDER BY id DESC")
    products = [dict(r) for r in cur.fetchall()]

    # Affiliate Offers count & performance
    cur.execute("SELECT * FROM affiliate_offers ORDER BY id DESC")
    offers = [dict(r) for r in cur.fetchall()]
    for off in offers:
        cur.execute("SELECT COUNT(*) as clicks FROM affiliate_clicks WHERE offer_id = ?", (off["id"],))
        off["clicks"] = cur.fetchone()["clicks"]
        cur.execute("SELECT COUNT(*) as convs, SUM(commission_earned) as earned FROM affiliate_conversions WHERE offer_id = ?", (off["id"],))
        conv_row = cur.fetchone()
        off["conversions"] = conv_row["convs"] or 0
        off["commission_earned"] = conv_row["earned"] or 0.0

    # Content Jobs
    cur.execute("SELECT * FROM content_jobs ORDER BY id DESC")
    content_jobs = [dict(r) for r in cur.fetchall()]

    # Experiment history
    cur.execute("SELECT * FROM experiments ORDER BY id DESC")
    experiments = [dict(r) for r in cur.fetchall()]

    # Financial reconciliation totals
    cur.execute("SELECT SUM(gross_amount) as gross, SUM(fee_amount) as fees, SUM(refund_amount) as refunds FROM orders WHERE is_test = 0")
    real_totals = dict(cur.fetchone())

    conn.close()

    return render_template(
        "portfolio.html",
        paper_portfolio=paper_portfolio,
        products=products,
        offers=offers,
        content_jobs=content_jobs,
        experiments=experiments,
        real_totals=real_totals
    )

@portfolio_bp.route("/api/portfolio/venture_metrics")
def api_venture_metrics():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as cnt FROM digital_products")
    total_products = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM affiliate_offers")
    total_offers = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM content_jobs WHERE status = 'completed'")
    completed_videos = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) as cnt FROM affiliate_clicks")
    affiliate_clicks = cur.fetchone()["cnt"]

    cur.execute("SELECT SUM(commission_earned) as comm FROM affiliate_conversions")
    comm_row = cur.fetchone()
    total_comm = round(comm_row["comm"] or 0.0, 2)

    cur.execute("SELECT SUM(gross_amount) as gross FROM orders WHERE is_test = 0")
    real_rev = round(cur.fetchone()["gross"] or 0.0, 2)

    conn.close()

    return jsonify({
        "total_digital_products": total_products,
        "total_affiliate_offers": total_offers,
        "completed_content_jobs": completed_videos,
        "total_affiliate_clicks": affiliate_clicks,
        "total_affiliate_commission": total_comm,
        "real_direct_revenue": real_rev,
        "total_venture_value": round(total_comm + real_rev, 2)
    })

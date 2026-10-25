import json
import re
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from flask import Blueprint, request, jsonify, render_template, send_file, abort
from datetime import datetime
import config
from database import get_db_connection
from services.ai_service import AIService
from services.gumroad_service import GumroadService
from services.digital_product_engine import DigitalProductEngine

products_bp = Blueprint("products", __name__)

def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", text)

def _get_gen_dir() -> Path:
    return Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()

@products_bp.route("/products")
def products_catalog():
    show_all = request.args.get("show_all") == "1" or request.args.get("admin") == "1"
    conn = get_db_connection()
    cur = conn.cursor()
    if show_all:
        cur.execute("SELECT * FROM digital_products ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM digital_products WHERE status != 'archived' AND is_test = 0 ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()

    products = []
    for r in rows:
        item = dict(r)
        try:
            item["contents"] = json.loads(item.get("contents_json") or "[]")
        except Exception:
            item["contents"] = []

        # Check physical files
        fp = item.get("file_path") or item.get("pdf_path")
        pdf_p = item.get("pdf_path")
        item["has_deliverable"] = bool(fp and Path(fp).exists())
        item["has_pdf"] = bool(pdf_p and Path(pdf_p).exists())

        if item["has_pdf"]:
            item["file_size_display"] = f"{round(Path(pdf_p).stat().st_size / 1024, 1)} KB"
        elif item["has_deliverable"]:
            item["file_size_display"] = f"{round(Path(fp).stat().st_size / 1024, 1)} KB"
        else:
            item["file_size_display"] = "No file"

        products.append(item)

    gumroad_status = GumroadService.get_status()
    ai_status = AIService.get_provider_status()

    return render_template(
        "products.html",
        products=products,
        show_all=show_all,
        gumroad_status=gumroad_status,
        ai_status=ai_status
    )

@products_bp.route("/products/<slug>")
def product_detail(slug):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM digital_products WHERE slug = ?", (slug,))
    row = cur.fetchone()
    conn.close()

    if not row:
        abort(404)

    product = dict(row)
    try:
        product["contents"] = json.loads(product.get("contents_json") or "[]")
    except Exception:
        product["contents"] = []

    fp = product.get("file_path") or product.get("pdf_path")
    pdf_p = product.get("pdf_path")
    product["has_deliverable"] = bool(fp and Path(fp).exists())
    product["has_pdf"] = bool(pdf_p and Path(pdf_p).exists())

    if product["has_pdf"]:
        product["file_size_display"] = f"{round(Path(pdf_p).stat().st_size / 1024, 1)} KB"
    elif product["has_deliverable"]:
        product["file_size_display"] = f"{round(Path(fp).stat().st_size / 1024, 1)} KB"
    else:
        product["file_size_display"] = "No file"

    # Read generation prompt and source markdown if available
    product_dir = _get_gen_dir() / "products" / slug
    prompt_file = product_dir / "generation_prompt.md"
    if prompt_file.exists():
        product["generation_prompt_text"] = prompt_file.read_text(encoding="utf-8", errors="ignore")
    else:
        product["generation_prompt_text"] = product.get("prompt_text")

    return render_template("product_detail.html", product=product)

@products_bp.route("/api/products/brief", methods=["POST"])
def api_generate_brief():
    """
    Derives a structured brief and inspectable Gemini prompt from a product idea.
    """
    data = request.get_json(silent=True) or {}
    idea = str(data.get("idea", "")).strip()
    audience = data.get("audience")
    product_intent = data.get("product_intent")
    title = data.get("title")
    format_type = str(data.get("format_type", "guide")).strip()
    max_pages = int(data.get("max_pages", 10))
    language = str(data.get("language", "English")).strip()
    price = float(data.get("price", 14.99))

    val = DigitalProductEngine.validate_idea(idea)
    if not val["valid"]:
        return jsonify({"success": False, "error": val["error"]}), 400

    try:
        brief = DigitalProductEngine.derive_brief(
            idea=idea,
            audience=audience,
            format_type=format_type,
            product_intent=product_intent,
            title=title,
            max_pages=max_pages,
            language=language,
            price=price
        )
        prompt = DigitalProductEngine.generate_prompt_from_brief(brief)
        return jsonify({
            "success": True,
            "brief": brief,
            "prompt": prompt
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@products_bp.route("/api/products/generate", methods=["POST"])
def api_generate_product():
    """
    Executes the full digital product generation pipeline:
    Brief -> Gemini content -> Semantic HTML -> Chromium PDF -> Validation -> SQLite -> Gumroad
    """
    data = request.get_json(silent=True) or {}
    idea = str(data.get("idea", "")).strip()
    audience = data.get("audience")
    product_intent = data.get("product_intent")
    title = data.get("title")
    format_type = str(data.get("format_type", "guide")).strip()
    max_pages = int(data.get("max_pages", 10))
    language = str(data.get("language", "English")).strip()
    price = float(data.get("price", 14.99))
    auto_publish_gumroad = bool(data.get("auto_publish_gumroad", False))
    custom_prompt = data.get("prompt")
    is_test = int(data.get("is_test", 0))

    val = DigitalProductEngine.validate_idea(idea)
    if not val["valid"]:
        return jsonify({"success": False, "error": val["error"]}), 400

    result = DigitalProductEngine.execute_product_generation(
        idea=idea,
        audience=audience,
        format_type=format_type,
        product_intent=product_intent,
        title=title,
        max_pages=max_pages,
        language=language,
        price=price,
        auto_publish_gumroad=auto_publish_gumroad,
        custom_prompt=custom_prompt,
        is_test=is_test
    )

    if not result.get("success"):
        return jsonify(result), 422

    return jsonify(result), 201

@products_bp.route("/api/products/<int:product_id>/sync_gumroad", methods=["POST"])
def api_sync_gumroad(product_id):
    """
    Explicitly synchronizes a product to Gumroad.
    """
    res = GumroadService.sync_product(product_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@products_bp.route("/api/products/<int:product_id>/publish_gumroad", methods=["POST"])
def api_publish_gumroad(product_id):
    """
    Explicitly attempts to publish a product live on Gumroad store.
    """
    res = GumroadService.publish_product(product_id)
    return jsonify(res), 200

@products_bp.route("/api/products/<int:product_id>/verify_attachment", methods=["POST"])
def api_verify_attachment(product_id):
    """
    Marks that the user has attached the physical PDF deliverable on Gumroad.
    """
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", True))
    res = GumroadService.mark_attachment_verified(product_id, user_confirmed=confirmed)
    status_code = 200 if res.get("success") else 404
    return jsonify(res), status_code

@products_bp.route("/api/gumroad/status", methods=["GET"])
def api_gumroad_status():
    """
    Returns Gumroad connection status without token leakage.
    """
    status = GumroadService.get_status(force_refresh=True)
    return jsonify(status)

@products_bp.route("/api/products", methods=["GET"])
def api_list_products():
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
    cur.execute(f"SELECT * FROM digital_products {where_clause} ORDER BY id DESC", params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for item in rows:
        try:
            item["contents"] = json.loads(item.get("contents_json") or "[]")
        except Exception:
            item["contents"] = []
        fp = item.get("file_path") or item.get("pdf_path")
        item["has_deliverable"] = bool(fp and Path(fp).exists())
        item["has_pdf"] = bool(item.get("pdf_path") and Path(item["pdf_path"]).exists())

    return jsonify({"products": rows, "count": len(rows)})

@products_bp.route("/api/products", methods=["POST"])
def api_create_product():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify({"error": "Product title is required"}), 400

    slug_base = slugify(title)
    audience = str(data.get("audience", "Solopreneurs")).strip()
    value_prop = str(data.get("value_proposition", "Actionable framework deliverable")).strip()
    description = str(data.get("description", "High-value digital asset produced by MINT.")).strip()
    product_type = str(data.get("product_type", "guide")).strip()
    price = float(data.get("price", 14.99))
    status = str(data.get("status", "ready")).strip().lower()
    if status not in ("draft", "ready", "needs_review", "published", "archived"):
        status = "ready"

    is_test = int(data.get("is_test", 0))
    contents = data.get("contents", ["Module 1: Foundations", "Module 2: Implementation", "Module 3: Checklists"])
    contents_json = json.dumps(contents)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()

    # Ensure unique slug
    slug = slug_base
    count = 1
    while True:
        cur.execute("SELECT id FROM digital_products WHERE slug = ?", (slug,))
        if not cur.fetchone():
            break
        slug = f"{slug_base}-{count}"
        count += 1

    cur.execute("""
        INSERT INTO digital_products (
            slug, title, product_type, audience, value_proposition,
            description, contents_json, price, status, is_test, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (slug, title, product_type, audience, value_prop, description, contents_json, price, status, is_test, now, now))

    product_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "product_id": product_id,
        "slug": slug,
        "message": f"Product '{title}' created successfully."
    }), 201

@products_bp.route("/api/products/<int:product_id>/status", methods=["PUT", "POST"])
def api_update_product_status(product_id):
    data = request.get_json(silent=True) or {}
    new_status = str(data.get("status", "")).strip().lower()
    if new_status not in ("draft", "ready", "needs_review", "published", "archived"):
        return jsonify({"error": "Invalid status. Must be draft, ready, needs_review, published, or archived."}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM digital_products WHERE id = ?", (product_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": f"Product #{product_id} not found."}), 404

    prod = dict(row)

    # Quality Gate Check before publishing
    if new_status == "published":
        issues = []
        if prod.get("is_test"):
            issues.append("Automated test records cannot be published to live catalog or Gumroad.")
        if len(prod.get("title", "")) < 5:
            issues.append("Title must be at least 5 characters.")
        if len(prod.get("description", "")) < 20:
            issues.append("Description must be at least 20 characters.")
        if prod.get("price", 0.0) <= 0:
            issues.append("Price must be greater than $0.00.")

        contents = []
        try:
            contents = json.loads(prod["contents_json"] or "[]")
        except Exception:
            pass
        if not contents:
            issues.append("Product must specify at least one structured module or chapter item.")

        fp = prod.get("file_path") or prod.get("pdf_path")
        if not fp or not Path(fp).exists():
            issues.append("Product deliverable file must exist before publishing.")
        elif Path(fp).stat().st_size <= 0:
            issues.append("Product deliverable file cannot be empty (0 bytes).")

        page_count = prod.get("page_count") or 0
        if page_count > 20:
            issues.append(f"Product exceeds 20-page maximum limit (has {page_count} pages).")

        quality_report = {}
        try:
            if prod.get("quality_report_json"):
                quality_report = json.loads(prod["quality_report_json"])
        except Exception:
            pass
        if quality_report and quality_report.get("passed") is False:
            issues.append("Product failed automated quality gate audit.")

        if issues:
            conn.close()
            return jsonify({
                "success": False,
                "error": "Quality Gate Failed",
                "issues": issues
            }), 422

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE digital_products SET status = ?, updated_at = ? WHERE id = ?", (new_status, now, product_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "product_id": product_id, "new_status": new_status})

@products_bp.route("/api/products/<int:product_id>/download", methods=["GET"])
@products_bp.route("/products/<slug>/download", methods=["GET"])
def download_product_deliverable(product_id: Optional[int] = None, slug: Optional[str] = None):
    """
    Path-traversal safe download endpoint for digital product packages.
    Prefers PDF deliverable, falls back to HTML deliverable if present.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    if product_id is not None:
        cur.execute("SELECT * FROM digital_products WHERE id = ?", (product_id,))
    elif slug:
        cur.execute("SELECT * FROM digital_products WHERE slug = ?", (slug,))
    else:
        conn.close()
        abort(404)

    row = cur.fetchone()
    conn.close()

    if not row:
        abort(404)

    prod = dict(row)
    gen_dir = _get_gen_dir()

    # Determine candidate deliverable file
    candidate_paths = []
    if prod.get("pdf_path"):
        candidate_paths.append(Path(prod["pdf_path"]))
    if prod.get("file_path"):
        candidate_paths.append(Path(prod["file_path"]))

    # Also check standard directory locations
    prod_slug = prod.get("slug")
    if prod_slug:
        candidate_paths.append(gen_dir / "products" / prod_slug / "product.pdf")
        candidate_paths.append(gen_dir / "products" / prod_slug / "render.html")
        candidate_paths.append(gen_dir / "products" / f"{prod_slug}_deliverable.html")

    target = None
    for cp in candidate_paths:
        if cp.exists() and cp.is_file():
            target = cp.resolve()
            break

    if not target:
        return jsonify({"error": "Product deliverable file is not available."}), 404

    # Path-traversal boundary check: must reside inside gen_dir
    try:
        target.relative_to(gen_dir)
    except ValueError:
        abort(403)

    mimetype = "application/pdf" if target.suffix.lower() == ".pdf" else "text/html"
    return send_file(
        str(target),
        mimetype=mimetype,
        as_attachment=True,
        download_name=target.name
    )

@products_bp.route("/api/products/<int:product_id>", methods=["DELETE"])
def api_delete_product(product_id: int):
    """
    Safe product deletion with reference auditing, path-traversal protection,
    and remote Gumroad warning.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM digital_products WHERE id = ?", (product_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": f"Product #{product_id} not found."}), 404

    prod = dict(row)
    title = prod.get("title", f"Product #{product_id}")
    slug = prod.get("slug", "")
    gen_dir = _get_gen_dir()
    products_base_dir = (gen_dir / "products").resolve()

    # 1. Audit foreign references to preserve accounting and experiment integrity
    has_orders = False
    cur.execute("SELECT COUNT(*) FROM orders WHERE product_title = ?", (title,))
    if cur.fetchone()[0] > 0:
        has_orders = True

    has_artifacts = False
    if slug:
        cur.execute("SELECT COUNT(*) FROM artifacts WHERE file_path LIKE ? OR meta_json LIKE ?", (f"%{slug}%", f"%{slug}%"))
        if cur.fetchone()[0] > 0:
            has_artifacts = True

    has_jobs = False
    cur.execute("SELECT COUNT(*) FROM content_jobs WHERE product_id = ?", (product_id,))
    if cur.fetchone()[0] > 0:
        has_jobs = True

    has_ig_posts = False
    try:
        cur.execute("SELECT COUNT(*) FROM instagram_posts WHERE product_id = ?", (product_id,))
        if cur.fetchone()[0] > 0:
            has_ig_posts = True
    except Exception:
        pass

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Gumroad warning
    gumroad_warning = None
    if prod.get("gumroad_id") or prod.get("gumroad_url"):
        g_ref = prod.get("gumroad_url") or f"ID: {prod.get('gumroad_id')}"
        gumroad_warning = (
            f"Remote Gumroad listing ({g_ref}) may remain active. "
            "MINT cannot automatically delete live listings from your Gumroad account; "
            "please unpublish or delete it directly on Gumroad."
        )

    # 2. If referenced, execute a soft-delete (archive) to maintain audit trails
    if has_orders or has_artifacts:
        cur.execute("UPDATE digital_products SET status = 'archived', updated_at = ? WHERE id = ?", (now_str, product_id))
        conn.commit()
        conn.close()
        return jsonify({
            "success": True,
            "action": "archived",
            "product_id": product_id,
            "message": f"Product '{title}' is referenced by financial or experiment history; archived safely to preserve audit logs.",
            "warning": gumroad_warning
        }), 200

    # 3. If unreferenced, safely remove physical files strictly within generated/products
    deleted_files = []
    # Dedicated directory check: generated/products/<slug>
    if slug:
        target_dir = (products_base_dir / slug).resolve()
        try:
            target_dir.relative_to(products_base_dir)
            if target_dir.exists() and target_dir.is_dir():
                for f in target_dir.iterdir():
                    if f.is_file():
                        # Check if another product references this exact file
                        cur.execute("SELECT COUNT(*) FROM digital_products WHERE id != ? AND (file_path = ? OR pdf_path = ?)", (product_id, str(f), str(f)))
                        if cur.fetchone()[0] == 0:
                            f.unlink()
                            deleted_files.append(f.name)
                # Remove empty dir
                if not any(target_dir.iterdir()):
                    target_dir.rmdir()
        except ValueError:
            conn.close()
            return jsonify({"error": "Path traversal violation detected on product slug directory."}), 403
        except Exception as e:
            pass

    # Single deliverable files check
    for key in ("file_path", "pdf_path", "preview_path"):
        fp = prod.get(key)
        if fp:
            target_file = Path(fp).resolve()
            try:
                target_file.relative_to(products_base_dir)
                if target_file.exists() and target_file.is_file():
                    cur.execute("SELECT COUNT(*) FROM digital_products WHERE id != ? AND (file_path = ? OR pdf_path = ? OR preview_path = ?)", (product_id, str(target_file), str(target_file), str(target_file)))
                    if cur.fetchone()[0] == 0:
                        target_file.unlink()
                        deleted_files.append(target_file.name)
            except (ValueError, Exception):
                pass

    # Physical deletion of row
    cur.execute("DELETE FROM digital_products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "action": "deleted",
        "product_id": product_id,
        "message": f"Product '{title}' permanently deleted.",
        "deleted_files": deleted_files,
        "warning": gumroad_warning
    }), 200

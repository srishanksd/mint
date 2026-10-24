import os
import json
import shutil
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_from_directory, send_file, abort

import config
from database import get_db_connection
from services.content_service import ContentStudioEngine, get_content_base_dir
from services.ai_image_service import AIImageService, get_images_base_dir
from services.social_service import InstagramService, YouTubeService
from services.media_hosting_service import MediaHostingService
from services.instagram_marketing_service import InstagramMarketingService, get_instagram_content_dir
from services.youtube_clipping_service import YouTubeClippingService
from services.youtube_scheduler_service import YouTubeSchedulerService

content_studio_bp = Blueprint("content_studio", __name__)


# ── Page View ────────────────────────────────────────────────────────────────
@content_studio_bp.route("/studio")
def studio_view():
    show_test = request.args.get("show_test") == "1"
    products = InstagramMarketingService.get_eligible_products()
    ig_posts = InstagramMarketingService.list_posts(limit=25, include_test=show_test)
    image_assets = AIImageService.list_images(limit=30, include_test=show_test)
    video_jobs = ContentStudioEngine.list_jobs(limit=20, include_test=show_test)

    ig_status = InstagramService.get_status()
    media_hosting = MediaHostingService.get_status()
    ai_image_status = AIImageService.get_status()
    yt_status = YouTubeService.get_status()
    yt_clips = YouTubeClippingService.list_clips(limit=30, include_test=show_test)
    yt_schedule = YouTubeSchedulerService.get_schedule_config()
    yt_scheduled_posts = YouTubeSchedulerService.list_scheduled_posts(limit=20, include_test=show_test)
    source_media = YouTubeClippingService.list_authorized_source_media()

    return render_template(
        "studio.html",
        products=products,
        ig_posts=ig_posts,
        image_assets=image_assets,
        video_jobs=video_jobs,
        ig_status=ig_status,
        media_hosting=media_hosting,
        ai_image_status=ai_image_status,
        yt_status=yt_status,
        yt_clips=yt_clips,
        yt_schedule=yt_schedule,
        yt_scheduled_posts=yt_scheduled_posts,
        source_media=source_media,
        show_test=show_test
    )


# ── Mode A: Instagram Product Marketing Endpoints ────────────────────────────
@content_studio_bp.route("/api/instagram/content/generate", methods=["POST"])
def api_generate_instagram_content():
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"success": False, "error": "A valid digital product must be selected."}), 400

    res = InstagramMarketingService.generate_marketing_post(data)
    status_code = 201 if res.get("success") else 422
    return jsonify(res), status_code


@content_studio_bp.route("/api/instagram/content", methods=["GET"])
def api_list_instagram_content():
    include_test = request.args.get("include_test") == "1" or request.args.get("show_test") == "1"
    limit = request.args.get("limit", 50, type=int)
    posts = InstagramMarketingService.list_posts(limit=limit, include_test=include_test)
    return jsonify({"posts": posts, "count": len(posts)})


@content_studio_bp.route("/api/instagram/content/<int:post_id>", methods=["GET"])
def api_get_instagram_content(post_id: int):
    post = InstagramMarketingService.get_post(post_id)
    if not post:
        return jsonify({"error": f"Instagram post #{post_id} not found."}), 404
    return jsonify({"post": post})


@content_studio_bp.route("/api/instagram/content/<int:post_id>/publish", methods=["POST"])
def api_publish_instagram_content(post_id: int):
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", False))
    if not confirmed:
        return jsonify({
            "success": False,
            "status": "confirmation_required",
            "error": "Publishing to Instagram requires explicit confirmation. Set confirmed: true."
        }), 400

    res = InstagramMarketingService.publish_post(post_id, confirmed=confirmed)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@content_studio_bp.route("/api/instagram/content/<int:post_id>", methods=["DELETE"])
def api_delete_instagram_content(post_id: int):
    res = InstagramMarketingService.delete_post(post_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@content_studio_bp.route("/api/instagram/content/<int:post_id>/files/<path:filename>", methods=["GET"])
def serve_instagram_post_file(post_id: int, filename: str):
    """
    Path-traversal safe media server for Instagram post files.
    """
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        abort(403)

    base_dir = get_instagram_content_dir().resolve()
    post_dir = (base_dir / str(post_id)).resolve()
    target_path = (post_dir / filename).resolve()

    try:
        target_path.relative_to(base_dir)
    except ValueError:
        abort(403)

    if not target_path.exists() or not target_path.is_file():
        abort(404)

    allowed_exts = {".jpg", ".jpeg", ".png", ".json"}
    if target_path.suffix.lower() not in allowed_exts:
        abort(403)

    mimetype = "image/jpeg" if target_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return send_file(str(target_path), mimetype=mimetype)


# ── Mode B: AI Image Generator Endpoints ─────────────────────────────────────
@content_studio_bp.route("/api/images/generate", methods=["POST"])
def api_generate_image():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"success": False, "error": "Image prompt is required."}), 400

    negative_prompt = data.get("negative_prompt")
    aspect_ratio = str(data.get("aspect_ratio", "1:1")).strip()
    resolution = str(data.get("resolution", "1024x1024")).strip()
    style = str(data.get("style", "photorealistic")).strip()
    is_test = int(data.get("is_test", 0))

    res = AIImageService.generate_image(
        prompt=prompt,
        negative_prompt=negative_prompt,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        style=style,
        is_test=is_test
    )
    status_code = 201 if res.get("success") else 422
    return jsonify(res), status_code


@content_studio_bp.route("/api/images", methods=["GET"])
def api_list_images():
    include_test = request.args.get("include_test") == "1" or request.args.get("show_test") == "1"
    limit = request.args.get("limit", 50, type=int)
    images = AIImageService.list_images(limit=limit, include_test=include_test)
    return jsonify({"images": images, "count": len(images)})


@content_studio_bp.route("/api/images/<int:image_id>", methods=["GET"])
def api_get_image(image_id: int):
    img = AIImageService.get_image(image_id)
    if not img:
        return jsonify({"error": f"Image #{image_id} not found."}), 404
    return jsonify({"image": img})


@content_studio_bp.route("/api/images/<int:image_id>", methods=["DELETE"])
def api_delete_image(image_id: int):
    res = AIImageService.delete_image(image_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@content_studio_bp.route("/api/images/<int:image_id>/file", methods=["GET"])
def serve_image_file(image_id: int):
    """
    Path-traversal safe endpoint to serve standalone AI generated images.
    """
    img = AIImageService.get_image(image_id)
    if not img or not img.get("file_path"):
        abort(404)

    base_dir = get_images_base_dir().resolve()
    target_path = Path(img["file_path"]).resolve()

    try:
        target_path.relative_to(base_dir)
    except ValueError:
        abort(403)

    if not target_path.exists() or not target_path.is_file():
        abort(404)

    mimetype = "image/jpeg" if target_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return send_file(str(target_path), mimetype=mimetype)


# ── Media Hosting & Status Endpoints ─────────────────────────────────────────
@content_studio_bp.route("/api/media-hosting/status", methods=["GET"])
def api_media_hosting_status():
    return jsonify(MediaHostingService.get_status())


# ── Legacy Video / Content Jobs Management ───────────────────────────────────
@content_studio_bp.route("/api/content/jobs", methods=["GET"])
def list_jobs():
    limit = request.args.get("limit", 50, type=int)
    show_test = request.args.get("include_test") == "1" or request.args.get("show_test") == "1"
    jobs = ContentStudioEngine.list_jobs(limit=limit, include_test=show_test)
    return jsonify({"jobs": jobs, "total": len(jobs)})


@content_studio_bp.route("/api/content/jobs", methods=["POST"])
def create_and_run_job():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify({"error": "Title is required for a content job"}), 400

    job_id = ContentStudioEngine.create_job(data)
    auto_execute = data.get("execute_now", True)
    if auto_execute:
        res = ContentStudioEngine.execute_job(job_id)
        return jsonify({
            "success": res.get("success", False),
            "job_id": job_id,
            "job": ContentStudioEngine.get_job(job_id),
            "execution": res
        })

    return jsonify({
        "success": True,
        "job_id": job_id,
        "job": ContentStudioEngine.get_job(job_id)
    }), 201


@content_studio_bp.route("/api/content/jobs/<int:job_id>", methods=["GET"])
def get_job_detail(job_id: int):
    job = ContentStudioEngine.get_job(job_id)
    if not job:
        return jsonify({"error": f"Job #{job_id} not found"}), 404
    return jsonify({"job": job})


@content_studio_bp.route("/api/content/jobs/<int:job_id>", methods=["DELETE"])
def delete_content_job(job_id: int):
    """
    Safely deletes a legacy content/video job and its files within its job directory.
    """
    job = ContentStudioEngine.get_job(job_id)
    if not job:
        return jsonify({"error": f"Job #{job_id} not found."}), 404

    base_dir = get_content_base_dir().resolve()
    job_dir = ContentStudioEngine.get_job_dir(job_id).resolve()

    # Safety: ensure job_dir is strictly within base_dir
    try:
        job_dir.relative_to(base_dir)
        if job_dir.exists() and job_dir.is_dir():
            shutil.rmtree(str(job_dir), ignore_errors=True)
    except ValueError:
        return jsonify({"error": "Refusing to delete directory outside content directory."}), 403
    except Exception as e:
        return jsonify({"error": f"Failed removing job files: {str(e)}"}), 500

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM content_jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Content job #{job_id} and its files were deleted."})


@content_studio_bp.route("/api/content/jobs/<int:job_id>/files/<path:filename>", methods=["GET"])
def serve_job_file(job_id, filename):
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        abort(403)

    job_dir = ContentStudioEngine.get_job_dir(job_id).resolve()
    target_path = (job_dir / filename).resolve()

    try:
        target_path.relative_to(job_dir)
    except ValueError:
        abort(403)

    if not target_path.exists() or not target_path.is_file():
        abort(404)

    allowed_exts = {".mp4", ".png", ".jpg", ".jpeg", ".json", ".wav", ".txt", ".srt"}
    if target_path.suffix.lower() not in allowed_exts:
        abort(403)

    return send_from_directory(str(job_dir), target_path.name)

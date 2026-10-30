"""
routes/youtube_clips.py
Dedicated Flask Blueprint for YouTube Clips Agent, OpenShorts MCP, and Local Free Video Clipper.
"""

import os
import json
import uuid
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file, abort
from werkzeug.utils import secure_filename

import config
from database import get_db_connection
from agents.youtube_clips_agent import YouTubeClipsAgent, get_youtube_clips_base_dir
from services.clipper_mcp_client import ClipperMCPClient
from services.local_clipper_service import LocalClipperService
from services.youtube_scheduler_service import YouTubeSchedulerService
from services.social_service import YouTubeService

youtube_clips_bp = Blueprint("youtube_clips", __name__)


# ── Page View ────────────────────────────────────────────────────────────────
@youtube_clips_bp.route("/youtube-clips")
@youtube_clips_bp.route("/youtube/clips")
def youtube_clips_view():
    show_test = request.args.get("show_test") == "1"

    # Auto-sync active processing projects so the page is always up to date
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM openshorts_jobs WHERE status = 'processing'")
        p_count = cur.fetchone()[0]
        conn.close()
        if p_count > 0:
            YouTubeClipsAgent.poll_and_sync_projects()
    except Exception as exc:
        pass

    agent_status = YouTubeClipsAgent.get_status()
    mcp_status = ClipperMCPClient.get_status()
    local_clipper = {
        "available": True,
        "engine": "faster-whisper + FFmpeg",
        "model": "llama3.2 / heuristic"
    }
    channels = YouTubeClipsAgent.list_source_channels()
    projects = YouTubeClipsAgent.list_projects(limit=20)
    clips = YouTubeClipsAgent.list_clips(limit=50, include_test=show_test)
    schedule_cfg = YouTubeSchedulerService.get_schedule_config()
    scheduled_posts = YouTubeSchedulerService.list_scheduled_posts(limit=30, include_test=show_test)
    upcoming_slots = YouTubeSchedulerService.calculate_next_slots(count=4)
    yt_destination = YouTubeService.get_status()

    active_job = None
    for p in projects:
        if p.get("status") == "processing":
            active_job = dict(p)
            try:
                raw_json = json.loads(p.get("raw_response_json") or "{}")
                active_job["stage"] = raw_json.get("stage", "processing")
                active_job["stage_label"] = raw_json.get("stage_label", "")
            except Exception:
                pass
            break

    return render_template(
        "youtube_clips.html",
        agent_status=agent_status,
        openshorts=mcp_status,
        local_clipper=local_clipper,
        channels=channels,
        projects=projects,
        clips=clips,
        schedule=schedule_cfg,
        scheduled_posts=scheduled_posts,
        upcoming_slots=upcoming_slots,
        yt_destination=yt_destination,
        active_job=active_job,
        current_page="youtube_clips"
    )


# ── API: Agent & Clipper Status ──────────────────────────────────────────────
@youtube_clips_bp.route("/api/youtube/clips/status", methods=["GET"])
def api_agent_status():
    return jsonify(YouTubeClipsAgent.get_status())


@youtube_clips_bp.route("/api/youtube/clipper/status", methods=["GET"])
@youtube_clips_bp.route("/api/clipper/usage", methods=["GET"])
def api_clipper_usage():
    mcp_status = ClipperMCPClient.get_status()
    return jsonify({
        "success": True,
        "can_clip": True,
        "provider": "openshorts_mcp" if mcp_status.get("server_running") else "local_free",
        "openshorts_mcp": mcp_status,
        "local_free": {
            "available": True,
            "engine": "faster-whisper + FFmpeg",
            "model": "llama3.2 / heuristic"
        }
    })


# ── API: Source Channel Discovery & Resolution ───────────────────────────────
@youtube_clips_bp.route("/api/youtube/channels/resolve", methods=["POST", "GET"])
def api_resolve_channel():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        query = str(data.get("query", "")).strip()
        rights_confirmed = bool(data.get("rights_confirmed", False))
    else:
        query = str(request.args.get("query", "")).strip()
        rights_confirmed = request.args.get("rights_confirmed") == "1"

    if not query:
        return jsonify({"success": False, "error": "Source channel query (name, handle or ID) is required."}), 400

    res = YouTubeClipsAgent.resolve_and_save_channel(query, rights_confirmed=rights_confirmed)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/channels", methods=["GET"])
def api_list_channels():
    channels = YouTubeClipsAgent.list_source_channels()
    return jsonify({"success": True, "channels": channels, "count": len(channels)})


@youtube_clips_bp.route("/api/youtube/channels/<channel_id>/videos", methods=["GET"])
def api_discover_channel_videos(channel_id: str):
    max_results = request.args.get("limit", 6, type=int)
    res = YouTubeClipsAgent.discover_recent_videos(channel_id=channel_id, max_results=max_results)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/videos/discovered", methods=["GET"])
def api_list_discovered_videos():
    channel_id = request.args.get("channel_id")
    limit = request.args.get("limit", 30, type=int)
    videos = YouTubeClipsAgent.list_discovered_videos(channel_id=channel_id, limit=limit)
    return jsonify({"success": True, "videos": videos, "count": len(videos)})


# ── API: OpenShorts MCP & Free Local Clipping Project Submission & Polling ──
@youtube_clips_bp.route("/api/youtube/clips/generate", methods=["POST"])
def api_generate_clips():
    data = request.get_json(silent=True) or {}
    video_url = str(data.get("video_url", "")).strip()
    video_title = data.get("video_title")
    source_channel_id = data.get("source_channel_id")
    source_channel_name = data.get("source_channel_name")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    provider = data.get("provider", "native_engine")
    is_test = int(data.get("is_test", 0))
    num_clips = int(data.get("num_clips", 2))
    min_duration = float(data.get("min_duration", 20.0))
    max_duration = float(data.get("max_duration", 55.0))
    framing_mode = str(data.get("framing_mode", "zoom_crop"))
    caption_style = str(data.get("caption_style", "beast"))
    async_mode = bool(data.get("async", False))

    if not video_url:
        return jsonify({"success": False, "error": "video_url is required."}), 400

    if async_mode and provider in ("native_engine", "auto"):
        from services.clipping.clipping_pipeline import ClippingPipeline
        job_id = ClippingPipeline.start_background_job(
            source=video_url,
            is_url=True,
            video_title=video_title or "",
            channel_id=source_channel_id or "youtube",
            channel_name=source_channel_name or "YouTube Source",
            start_time=start_time,
            end_time=end_time,
            num_clips=num_clips,
            min_duration=min_duration,
            max_duration=max_duration,
            framing_mode=framing_mode,
            caption_style=caption_style,
            is_test=is_test
        )
        return jsonify({
            "success": True,
            "status": "processing",
            "job_id": job_id,
            "project_id": job_id,
            "message": "Native AI clipping job started in background."
        }), 200

    res = YouTubeClipsAgent.submit_clipping_job(
        video_url_or_id=video_url,
        video_title=video_title,
        source_channel_id=source_channel_id,
        source_channel_name=source_channel_name,
        start_time=start_time,
        end_time=end_time,
        provider=provider,
        is_test=is_test,
        num_clips=num_clips,
        min_duration=min_duration,
        max_duration=max_duration,
        framing_mode=framing_mode,
        caption_style=caption_style
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/clips/upload", methods=["POST"])
def api_upload_and_clip():
    """Uploads a local video file from user's machine and immediately processes it with LocalClipperService."""
    if "video_file" not in request.files:
        return jsonify({"success": False, "error": "No video file uploaded."}), 400
    file = request.files["video_file"]
    if not file or not file.filename:
        return jsonify({"success": False, "error": "Empty filename."}), 400

    filename = secure_filename(file.filename)
    allowed_exts = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
    if not filename.lower().endswith(allowed_exts):
        return jsonify({"success": False, "error": f"Unsupported video format. Allowed: {', '.join(allowed_exts)}"}), 400

    upload_dir = Path(getattr(config, "DATA_DIR", None) or Path(__file__).resolve().parent.parent / "data") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{uuid.uuid4().hex[:8]}_{filename}"
    file.save(str(saved_path))

    video_title = request.form.get("video_title") or Path(filename).stem
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")

    st_val = float(start_time) if start_time not in (None, "") else None
    et_val = float(end_time) if end_time not in (None, "") else None

    res = LocalClipperService.create_local_clip_job(
        source_file_path=str(saved_path),
        video_title=video_title,
        channel_name="Local Upload",
        channel_id="local",
        rights_confirmed=True,
        start_time=st_val,
        end_time=et_val
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_clips_bp.route("/api/clipper/projects/<project_id>", methods=["GET"])
def api_get_single_project(project_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM openshorts_jobs WHERE job_id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "error": "Project not found"}), 404
    p = dict(row)
    stage = "processing"
    stage_label = ""
    try:
        raw_json = json.loads(p.get("raw_response_json") or "{}")
        stage = raw_json.get("stage", "processing")
        stage_label = raw_json.get("stage_label", "")
    except Exception:
        pass
    p["stage"] = stage
    p["stage_label"] = stage_label
    return jsonify({"success": True, "project": p})

@youtube_clips_bp.route("/api/clipper/projects", methods=["GET"])
def api_list_projects():
    projects = YouTubeClipsAgent.list_projects()
    return jsonify({"success": True, "projects": projects, "count": len(projects)})


@youtube_clips_bp.route("/api/clipper/projects/poll", methods=["POST", "GET"])
def api_poll_projects():
    data = request.get_json(silent=True) or {}
    force_all = bool(data.get("force_all") or request.args.get("force_all") in ("1", "true"))
    project_id = data.get("project_id") or request.args.get("project_id")
    if project_id:
        res = YouTubeClipsAgent.sync_project(project_id)
    else:
        res = YouTubeClipsAgent.poll_and_sync_projects(force_all=force_all)
    return jsonify(res)


@youtube_clips_bp.route("/api/clipper/projects/<project_id>/sync", methods=["POST"])
def api_sync_project(project_id: str):
    res = YouTubeClipsAgent.sync_project(project_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/clipper/projects/<project_id>/retry", methods=["POST"])
def api_retry_project(project_id: str):
    data = request.get_json(silent=True) or {}
    new_video_url = data.get("video_url")
    new_video_title = data.get("video_title")
    confirmed = bool(data.get("confirmed", False))
    res = YouTubeClipsAgent.retry_project(
        project_id=project_id,
        new_video_url=new_video_url,
        new_video_title=new_video_title,
        confirmed=confirmed
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/clipper/projects/<project_id>/delete", methods=["POST", "DELETE"])
@youtube_clips_bp.route("/api/clipper/projects/<project_id>", methods=["DELETE"])
def api_delete_project(project_id: str):
    res = YouTubeClipsAgent.delete_project(project_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_clips_bp.route("/api/clipper/projects/clear-failed", methods=["POST"])
def api_clear_failed_projects():
    res = YouTubeClipsAgent.clear_failed_projects()
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


# ── API: Clip Queue & Approval ───────────────────────────────────────────────
@youtube_clips_bp.route("/api/youtube/clips", methods=["GET"])
def api_list_clips():
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)
    include_test = request.args.get("include_test") == "1" or request.args.get("show_test") == "1"
    clips = YouTubeClipsAgent.list_clips(status=status, limit=limit, include_test=include_test)
    return jsonify({"success": True, "clips": clips, "count": len(clips)})


@youtube_clips_bp.route("/api/youtube/clips/<int:clip_id>/approve", methods=["POST"])
def api_approve_clip(clip_id: int):
    res = YouTubeClipsAgent.approve_clip(clip_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/clips/<int:clip_id>/reject", methods=["POST"])
def api_reject_clip(clip_id: int):
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason", "")).strip()
    res = YouTubeClipsAgent.reject_clip(clip_id, reason=reason)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/clips/<int:clip_id>", methods=["DELETE"])
def api_delete_clip(clip_id: int):
    res = YouTubeClipsAgent.delete_clip(clip_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/clips/<int:clip_id>/publish-now", methods=["POST"])
def api_publish_clip_now(clip_id: int):
    """
    On-demand instant publication to YouTube as public for live demonstration to judges.
    """
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", True))
    privacy_status = str(data.get("privacy_status", "public")).strip()
    res = YouTubeClipsAgent.publish_clip_now(clip_id, privacy_status=privacy_status, confirmed=confirmed)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/clips/<int:clip_id>/file", methods=["GET"])
def serve_clip_file(clip_id: int):
    """
    Path-traversal safe endpoint to serve downloaded clip MP4.
    """
    conn = YouTubeClipsAgent.list_clips(limit=500, include_test=True)
    target_clip = next((c for c in conn if c["id"] == clip_id), None)
    if not target_clip or not target_clip.get("output_path"):
        abort(404)

    file_path = Path(target_clip["output_path"]).resolve()
    base_dir = get_youtube_clips_base_dir().resolve()

    try:
        file_path.relative_to(base_dir)
    except ValueError:
        # Fallback check if in legacy clips folder
        legacy_dir = (base_dir.parent / "clips").resolve()
        try:
            file_path.relative_to(legacy_dir)
        except ValueError:
            abort(403)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    return send_file(str(file_path), mimetype="video/mp4", conditional=True)


@youtube_clips_bp.route("/api/youtube/clips/<int:clip_id>/thumbnail", methods=["GET"])
def serve_clip_thumbnail(clip_id: int):
    """
    Path-traversal safe endpoint to serve generated clip thumbnail JPEG.
    """
    conn = YouTubeClipsAgent.list_clips(limit=500, include_test=True)
    target_clip = next((c for c in conn if c["id"] == clip_id), None)
    if not target_clip:
        abort(404)

    thumb_val = target_clip.get("thumbnail_url")
    if not thumb_val or not os.path.exists(thumb_val):
        abort(404)

    thumb_path = Path(thumb_val).resolve()
    base_dir = get_youtube_clips_base_dir().resolve()
    try:
        thumb_path.relative_to(base_dir)
    except ValueError:
        abort(403)

    return send_file(str(thumb_path), mimetype="image/jpeg")


# ── API: Schedule Management ─────────────────────────────────────────────────
@youtube_clips_bp.route("/api/youtube/schedule", methods=["GET"])
def api_get_schedule():
    cfg = YouTubeSchedulerService.get_schedule_config()
    upcoming = YouTubeSchedulerService.calculate_next_slots(count=4)
    return jsonify({"schedule": cfg, "upcoming_slots": upcoming})


@youtube_clips_bp.route("/api/youtube/schedule", methods=["POST"])
def api_update_schedule():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    timezone_str = str(data.get("timezone", "Asia/Kolkata")).strip()
    slot_1 = str(data.get("slot_1_time", "10:00")).strip()
    slot_2 = str(data.get("slot_2_time", "18:00")).strip()
    timing_src = str(data.get("audience_timing_source", "user_configured_studio")).strip()
    auto_pub = bool(data.get("auto_publish", False))
    max_daily = int(data.get("max_daily_posts", 2))
    queue_tgt = int(data.get("queue_target", 6))

    cfg = YouTubeSchedulerService.update_schedule_config(
        enabled=enabled,
        timezone_str=timezone_str,
        slot_1_time=slot_1,
        slot_2_time=slot_2,
        audience_timing_source=timing_src,
        auto_publish=auto_pub,
        max_daily_posts=max_daily,
        queue_target=queue_tgt
    )
    # Sync slots if enabled
    if enabled:
        YouTubeSchedulerService.sync_schedule_slots()

    return jsonify({"success": True, "schedule": cfg})


@youtube_clips_bp.route("/api/youtube/schedule/posts", methods=["GET"])
def api_list_scheduled_posts():
    limit = request.args.get("limit", 50, type=int)
    include_test = request.args.get("include_test") == "1"
    posts = YouTubeSchedulerService.list_scheduled_posts(limit=limit, include_test=include_test)
    return jsonify({"posts": posts, "count": len(posts)})


@youtube_clips_bp.route("/api/youtube/schedule/posts/<int:post_id>/publish", methods=["POST"])
def api_publish_scheduled_post(post_id: int):
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", False))
    publish_now = bool(data.get("publish_now", False))
    privacy_status = str(data.get("privacy_status", "public")).strip()
    res = YouTubeSchedulerService.publish_scheduled_post(
        post_id,
        confirmed=confirmed,
        publish_now=publish_now,
        privacy_status=privacy_status
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code



@youtube_clips_bp.route("/api/youtube/schedule/posts/<int:post_id>", methods=["DELETE"])
def api_cancel_scheduled_post(post_id: int):
    res = YouTubeSchedulerService.cancel_scheduled_post(post_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


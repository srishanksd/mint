"""
routes/youtube_clips.py
Dedicated Flask Blueprint for YouTube Clips Agent and LumiClip Integration.
"""

import os
import json
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file, abort

from agents.youtube_clips_agent import YouTubeClipsAgent
from services.lumiclip_service import LumiClipService, get_youtube_clips_base_dir
from services.youtube_scheduler_service import YouTubeSchedulerService
from services.social_service import YouTubeService

youtube_clips_bp = Blueprint("youtube_clips", __name__)


# ── Page View ────────────────────────────────────────────────────────────────
@youtube_clips_bp.route("/youtube-clips")
def youtube_clips_view():
    show_test = request.args.get("show_test") == "1"

    # Auto-sync active processing projects so the page is always up to date
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM lumiclip_projects WHERE status = 'processing'")
        p_count = cur.fetchone()[0]
        conn.close()
        if p_count > 0:
            YouTubeClipsAgent.poll_and_sync_projects()
    except Exception as exc:
        logger.warning("Error auto-polling LumiClip projects on page load: %s", exc)

    agent_status = YouTubeClipsAgent.get_status()
    lumiclip_status = LumiClipService.get_status(force_refresh=True)
    channels = YouTubeClipsAgent.list_source_channels()
    projects = YouTubeClipsAgent.list_projects(limit=20)
    clips = YouTubeClipsAgent.list_clips(limit=50, include_test=show_test)
    schedule_cfg = YouTubeSchedulerService.get_schedule_config()
    scheduled_posts = YouTubeSchedulerService.list_scheduled_posts(limit=30, include_test=show_test)
    upcoming_slots = YouTubeSchedulerService.calculate_next_slots(count=4)
    yt_destination = YouTubeService.get_status()

    return render_template(
        "youtube_clips.html",
        agent_status=agent_status,
        lumiclip=lumiclip_status,
        channels=channels,
        projects=projects,
        clips=clips,
        schedule=schedule_cfg,
        scheduled_posts=scheduled_posts,
        upcoming_slots=upcoming_slots,
        yt_destination=yt_destination,
        current_page="youtube_clips"
    )


# ── API: Agent & LumiClip Status ─────────────────────────────────────────────
@youtube_clips_bp.route("/api/youtube/clips/status", methods=["GET"])
def api_agent_status():
    return jsonify(YouTubeClipsAgent.get_status())


@youtube_clips_bp.route("/api/lumiclip/usage", methods=["GET"])
def api_lumiclip_usage():
    force_refresh = request.args.get("refresh") == "1" or request.args.get("force_refresh") == "1"
    return jsonify(LumiClipService.get_status(force_refresh=force_refresh))


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


# ── API: LumiClip Project Submission & Polling ───────────────────────────────
@youtube_clips_bp.route("/api/youtube/clips/generate", methods=["POST"])
def api_generate_clips():
    data = request.get_json(silent=True) or {}
    video_url = str(data.get("video_url", "")).strip()
    video_title = data.get("video_title")
    source_channel_id = data.get("source_channel_id")
    source_channel_name = data.get("source_channel_name")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    is_test = int(data.get("is_test", 0))

    if not video_url:
        return jsonify({"success": False, "error": "video_url is required."}), 400

    res = YouTubeClipsAgent.submit_clipping_job(
        video_url_or_id=video_url,
        video_title=video_title,
        source_channel_id=source_channel_id,
        source_channel_name=source_channel_name,
        start_time=start_time,
        end_time=end_time,
        is_test=is_test
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_clips_bp.route("/api/lumiclip/projects", methods=["GET"])
def api_list_projects():
    projects = YouTubeClipsAgent.list_projects()
    return jsonify({"success": True, "projects": projects, "count": len(projects)})


@youtube_clips_bp.route("/api/lumiclip/projects/poll", methods=["POST", "GET"])
def api_poll_projects():
    data = request.get_json(silent=True) or {}
    force_all = bool(data.get("force_all") or request.args.get("force_all") in ("1", "true"))
    project_id = data.get("project_id") or request.args.get("project_id")
    if project_id:
        res = YouTubeClipsAgent.sync_project(project_id)
    else:
        res = YouTubeClipsAgent.poll_and_sync_projects(force_all=force_all)
    return jsonify(res)


@youtube_clips_bp.route("/api/lumiclip/projects/<project_id>/sync", methods=["POST"])
def api_sync_project(project_id: str):
    res = YouTubeClipsAgent.sync_project(project_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_clips_bp.route("/api/lumiclip/projects/<project_id>/retry", methods=["POST"])
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


@youtube_clips_bp.route("/api/youtube/clips/synthesize", methods=["POST"])
def api_synthesize_clip():
    """
    Synthesizes a compliant 9:16 vertical Short immediately when cloud processing is restricted.
    """
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    title = data.get("title") or data.get("video_title")
    channel_name = data.get("channel_name") or data.get("source_channel_name")
    duration = float(data.get("duration", 12.0))

    res = YouTubeClipsAgent.synthesize_publishable_short(
        project_id=project_id,
        title=title,
        channel_name=channel_name,
        duration_sec=duration
    )
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

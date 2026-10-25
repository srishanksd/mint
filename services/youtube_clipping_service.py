"""
services/youtube_clipping_service.py
YouTube Channel Resolution, Authorized Media Validation, and 9:16 Clipping Engine for MINT.

Adheres strictly to YouTube API Services Developer Policies:
- Never downloads or rips audiovisual content from YouTube URLs.
- Processes original user-supplied source files, MINT-rendered deliverables,
  and licensed media with explicit user rights confirmation.
- Uses official YouTube Data API v3 for channel resolution and metadata.
- Uses FFmpeg for vertical 9:16 video segment rendering.
"""

import os
import re
import json
import subprocess
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import config
from database import get_db_connection
from routes.youtube_auth import _load_token, _refresh_if_needed, _build_youtube_client

logger = logging.getLogger(__name__)


def get_clips_base_dir() -> Path:
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    clips_dir = gen_dir / "content" / "youtube_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    return clips_dir


def get_source_videos_dir() -> Path:
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    src_dir = gen_dir / "content" / "youtube_clips" / "source_videos"
    src_dir.mkdir(parents=True, exist_ok=True)
    return src_dir


def get_videos_dir() -> Path:
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    v_dir = gen_dir / "content" / "youtube_clips"
    v_dir.mkdir(parents=True, exist_ok=True)
    return v_dir


class YouTubeClippingService:

    @classmethod
    def resolve_source_channel(cls, query: str) -> Dict[str, Any]:
        """
        Uses YouTube Data API v3 to identify and verify the source channel.
        Accepts channel handle (e.g. @channel), channel ID (UC...), or channel title.
        """
        q = (query or "").strip()
        if not q:
            return {"success": False, "error": "Channel name or handle is required."}

        creds = _load_token("youtube")
        if not creds:
            return {
                "success": False,
                "error": "YouTube OAuth is not connected. Connect YouTube in the dashboard first to resolve channel metadata.",
            }

        try:
            creds = _refresh_if_needed(creds)
            yt = _build_youtube_client(creds)

            clean_q = q.lstrip("@")

            # Try by handle if starts with @
            channel_item = None
            if q.startswith("@"):
                try:
                    res = yt.channels().list(part="snippet,statistics", forHandle=clean_q).execute()
                    items = res.get("items", [])
                    if items:
                        channel_item = items[0]
                except Exception:
                    channel_item = None

            # Try by channel ID if starts with UC
            if not channel_item and q.startswith("UC") and len(q) >= 20:
                try:
                    res = yt.channels().list(part="snippet,statistics", id=q).execute()
                    items = res.get("items", [])
                    if items:
                        channel_item = items[0]
                except Exception:
                    channel_item = None

            # Try by search if not yet resolved
            if not channel_item:
                res = yt.search().list(part="snippet", q=q, type="channel", maxResults=3).execute()
                items = res.get("items", [])
                if items:
                    ch_id = items[0]["snippet"]["channelId"]
                    detail = yt.channels().list(part="snippet,statistics", id=ch_id).execute()
                    d_items = detail.get("items", [])
                    if d_items:
                        channel_item = d_items[0]

            if not channel_item:
                return {
                    "success": False,
                    "error": f"No YouTube channel found matching '{q}'. Please check the handle or name.",
                }

            snippet = channel_item.get("snippet", {})
            stats = channel_item.get("statistics", {})
            ch_id = channel_item.get("id")
            custom_url = snippet.get("customUrl") or f"@{clean_q}"

            return {
                "success": True,
                "channel_id": ch_id,
                "title": snippet.get("title"),
                "handle": custom_url,
                "description": snippet.get("description", "")[:300],
                "subscriber_count": stats.get("subscriberCount", "Hidden"),
                "video_count": stats.get("videoCount", "0"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url"),
                "channel_url": f"https://www.youtube.com/channel/{ch_id}",
            }

        except Exception as exc:
            logger.exception("Error resolving YouTube channel")
            return {"success": False, "error": f"YouTube Data API error: {str(exc)}"}

    @classmethod
    def list_authorized_source_media(cls) -> List[Dict[str, Any]]:
        """
        Lists actual authorized local MP4 files available for clipping.
        Scans generated/source_videos, generated/videos, and generated/content.
        """
        gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()
        media_list = []
        seen_paths = set()

        search_dirs = [
            get_source_videos_dir(),
            get_videos_dir(),
            gen_dir / "content" / "jobs" / "12",
        ]

        for s_dir in search_dirs:
            if not s_dir.exists():
                continue
            for mp4 in s_dir.rglob("*.mp4"):
                r_path = str(mp4.resolve())
                if r_path in seen_paths:
                    continue
                seen_paths.add(r_path)

                size_mb = round(mp4.stat().st_size / (1024 * 1024), 2)
                duration_sec = cls._get_video_duration(str(mp4))

                media_list.append({
                    "filename": mp4.name,
                    "relative_path": str(mp4.relative_to(gen_dir)),
                    "full_path": r_path,
                    "size_mb": size_mb,
                    "duration_sec": duration_sec,
                    "modified_at": datetime.fromtimestamp(mp4.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })

        media_list.sort(key=lambda m: m["modified_at"], reverse=True)
        return media_list

    @classmethod
    def _get_video_duration(cls, file_path: str) -> float:
        """Runs ffprobe to safely determine video duration."""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return round(float(result.stdout.strip()), 2)
        except Exception:
            pass
        return 0.0

    @classmethod
    def render_clip(
        cls,
        source_path: str,
        start_sec: float,
        end_sec: float,
        clip_title: str,
        source_channel_name: Optional[str] = None,
        source_channel_id: Optional[str] = None,
        source_video_ref: Optional[str] = None,
        rights_confirmed: bool = False,
        aspect_ratio: str = "9:16",
        clip_description: Optional[str] = None,
        hashtags: Optional[str] = None,
        is_test: int = 0
    ) -> Dict[str, Any]:
        """
        Renders a vertical 9:16 clip from an authorized local source video using FFmpeg.
        Strictly requires rights_confirmed=True.
        """
        if not rights_confirmed:
            return {
                "success": False,
                "error": "You must confirm ownership or authorized reuse rights for this source video before clipping."
            }

        title = (clip_title or "").strip()
        if not title:
            return {"success": False, "error": "Clip title cannot be blank."}

        if start_sec < 0 or end_sec <= start_sec:
            return {"success": False, "error": f"Invalid clip segment ({start_sec}s to {end_sec}s). End time must be greater than start time."}

        duration = round(end_sec - start_sec, 2)
        if duration > 180:
            return {"success": False, "error": "Clip length exceeds maximum supported limit of 180 seconds for vertical clips."}

        # Validate source path
        src_file = Path(source_path).resolve()
        if not src_file.exists() or not src_file.is_file():
            # Check relative to generated
            gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()
            candidate = (gen_dir / source_path).resolve()
            if candidate.exists() and candidate.is_file():
                src_file = candidate
            else:
                return {"success": False, "error": f"Source video file not found: {source_path}"}

        # Check boundary security
        gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()
        try:
            src_file.relative_to(gen_dir)
        except ValueError:
            return {"success": False, "error": "Refusing to process media outside permitted project directory."}

        # Reserve clip row in database
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean_hashtags = (hashtags or "#shorts #automation #mint #digitalventure").strip()
        desc = (clip_description or f"{title}\n\n{clean_hashtags}").strip()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (
                source_channel_name, source_channel_id, source_video_ref,
                source_file_path, rights_confirmed, clip_title, clip_description,
                hashtags, aspect_ratio, start_time_sec, end_time_sec,
                duration_sec, output_path, status, is_test, created_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, '', 'rendering', ?, ?)
        """, (
            source_channel_name, source_channel_id, source_video_ref or src_file.name,
            str(src_file), title, desc, clean_hashtags, aspect_ratio,
            start_sec, end_sec, duration, is_test, now_str
        ))
        clip_id = cur.lastrowid
        conn.commit()

        # Destination path: generated/content/youtube_clips/<clip_id>/clip_<clip_id>.mp4
        clip_dir = get_clips_base_dir() / str(clip_id)
        clip_dir.mkdir(parents=True, exist_ok=True)
        out_mp4 = clip_dir / f"clip_{clip_id}.mp4"

        # Delegate vertical 9:16 transcode to authoritative LocalClipperService
        from services.local_clipper_service import LocalClipperService
        render_ok = LocalClipperService.render_vertical_clip(
            input_path=str(src_file),
            start_sec=start_sec,
            end_sec=end_sec,
            output_path=str(out_mp4)
        )

        if not render_ok or not out_mp4.exists() or out_mp4.stat().st_size == 0:
            err_msg = "FFmpeg finished but output MP4 file was not generated or is empty."
            cur.execute("UPDATE youtube_clips SET status = 'failed', error_message = ? WHERE id = ?", (err_msg, clip_id))
            conn.commit()
            conn.close()
            return {"success": False, "error": err_msg}

        actual_size = out_mp4.stat().st_size
        actual_dur = cls._get_video_duration(str(out_mp4)) or duration

        cur.execute("""
            UPDATE youtube_clips
            SET output_path = ?, file_size_bytes = ?, duration_sec = ?, status = 'rendered', error_message = NULL
            WHERE id = ?
        """, (str(out_mp4), actual_size, actual_dur, clip_id))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "clip_id": clip_id,
            "title": title,
            "status": "rendered",
            "duration_sec": actual_dur,
            "file_size_bytes": actual_size,
            "file_path": str(out_mp4),
            "file_url": f"/api/youtube/clips/{clip_id}/file",
            "created_at": now_str,
        }

    @classmethod
    def list_clips(cls, limit: int = 50, include_test: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        q = "SELECT * FROM youtube_clips"
        params = []
        if not include_test:
            q += " WHERE is_test = 0"
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur.execute(q, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for c in rows:
            op = c.get("output_path")
            c["exists"] = bool(op and Path(op).exists())
            c["file_url"] = f"/api/youtube/clips/{c['id']}/file" if c["exists"] else None
        return rows

    @classmethod
    def get_clip(cls, clip_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_clips WHERE id = ?", (clip_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        c = dict(row)
        op = c.get("output_path")
        c["exists"] = bool(op and Path(op).exists())
        c["file_url"] = f"/api/youtube/clips/{c['id']}/file" if c["exists"] else None
        return c

    @classmethod
    def delete_clip(cls, clip_id: int) -> Dict[str, Any]:
        """Safely removes rendered clip file and its record if not referenced by active schedule."""
        clip = cls.get_clip(clip_id)
        if not clip:
            return {"success": False, "error": f"Clip #{clip_id} not found."}

        conn = get_db_connection()
        cur = conn.cursor()

        # Check references in youtube_scheduled_posts
        cur.execute("SELECT id, status, scheduled_time FROM youtube_scheduled_posts WHERE clip_id = ?", (clip_id,))
        scheduled = cur.fetchall()
        for s in scheduled:
            if s["status"] in ("queued", "uploading", "scheduled_api"):
                conn.close()
                return {
                    "success": False,
                    "error": f"Clip #{clip_id} is currently queued for publishing at {s['scheduled_time']} (Post #{s['id']}). Cancel the scheduled post first."
                }

        # Safe file removal
        op = clip.get("output_path")
        if op:
            target = Path(op).resolve()
            base_dir = get_clips_base_dir().resolve()
            gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()
            is_safe = False
            for safe_dir in (base_dir, gen_dir):
                try:
                    target.relative_to(safe_dir)
                    is_safe = True
                    break
                except ValueError:
                    pass

            if not is_safe:
                conn.close()
                return {"success": False, "error": "Refusing to delete file outside clips directory."}

            try:
                if target.exists() and target.is_file():
                    target.unlink()
                parent = target.parent
                if parent not in (base_dir, gen_dir) and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except Exception as e:
                logger.warning("Error deleting clip file: %s", e)

        cur.execute("DELETE FROM youtube_clips WHERE id = ?", (clip_id,))
        conn.commit()
        conn.close()

        return {"success": True, "message": f"Clip #{clip_id} was deleted."}

"""
services/youtube_scheduler_service.py
Persistent Twice-Daily YouTube Publishing Scheduler for MINT.

Official Google references:
- YouTube Data API v3 videos.insert: https://developers.google.com/youtube/v3/docs/videos/insert
- Status.publishAt (RFC 3339 ISO 8601 UTC timestamp): requires status.privacyStatus='private'
- YouTube Analytics API: https://developers.google.com/youtube/analytics/

Features:
- Two daily publishing slots (user-configured from YouTube Studio audience heatmap).
- Persistent queue in SQLite (youtube_schedules and youtube_scheduled_posts).
- Idempotent upload: prevents double-posting the same clip.
- Offline gap detection: marks missed slots without bursting uploads on restart.
- Honest analytics reporting: never claims hourly heatmap from standard API.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import googleapiclient.discovery
import googleapiclient.http
import googleapiclient.errors

import config
from database import get_db_connection, log_activity
from routes.youtube_auth import _load_token, _refresh_if_needed, _build_youtube_client

logger = logging.getLogger(__name__)

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


class YouTubeSchedulerService:

    @classmethod
    def get_schedule_config(cls) -> Dict[str, Any]:
        """Returns the current twice-daily schedule settings from SQLite."""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_schedules ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()

        if not row:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                INSERT INTO youtube_schedules (
                    enabled, timezone, slot_1_time, slot_2_time,
                    audience_timing_source, status, updated_at
                ) VALUES (0, 'UTC', '10:00', '18:00', 'user_configured_studio', 'idle', ?)
            """, (now_str,))
            conn.commit()
            cur.execute("SELECT * FROM youtube_schedules ORDER BY id ASC LIMIT 1")
            row = cur.fetchone()

        cfg = dict(row)
        conn.close()
        return cfg

    @classmethod
    def update_schedule_config(
        cls,
        enabled: bool,
        timezone_str: str = "UTC",
        slot_1_time: str = "10:00",
        slot_2_time: str = "18:00",
        audience_timing_source: str = "user_configured_studio"
    ) -> Dict[str, Any]:
        """Updates twice-daily schedule configuration."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM youtube_schedules ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()

        if row:
            cur.execute("""
                UPDATE youtube_schedules
                SET enabled = ?, timezone = ?, slot_1_time = ?, slot_2_time = ?,
                    audience_timing_source = ?, updated_at = ?
                WHERE id = ?
            """, (1 if enabled else 0, timezone_str, slot_1_time, slot_2_time, audience_timing_source, now_str, row["id"]))
        else:
            cur.execute("""
                INSERT INTO youtube_schedules (
                    enabled, timezone, slot_1_time, slot_2_time,
                    audience_timing_source, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'idle', ?)
            """, (1 if enabled else 0, timezone_str, slot_1_time, slot_2_time, audience_timing_source, now_str))

        conn.commit()
        conn.close()
        return cls.get_schedule_config()

    @classmethod
    def get_analytics_audience_status(cls) -> Dict[str, Any]:
        """
        Queries official YouTube Analytics API if the required scope is authorized.
        Honestly reports that hourly viewer heatmaps are only available inside YouTube Studio,
        not through standard Analytics API time dimensions.
        """
        creds = _load_token("youtube")
        if not creds:
            return {
                "authorized": False,
                "has_scope": False,
                "message": "YouTube not connected. Authorize YouTube to check analytics."
            }

        granted_scopes = set(creds.scopes or [])
        has_analytics_scope = ANALYTICS_SCOPE in granted_scopes

        if not has_analytics_scope:
            return {
                "authorized": True,
                "has_scope": False,
                "message": "YouTube Analytics scope (yt-analytics.readonly) not granted. Re-authorize to enable read-only analytics checks.",
                "timing_source": "user_configured_studio",
                "notice": "Standard YouTube Analytics API does not expose hourly heatmaps; use your YouTube Studio audience report to set the two peak slots."
            }

        try:
            creds = _refresh_if_needed(creds)
            yt_analytics = googleapiclient.discovery.build(
                "youtubeAnalytics", "v2", credentials=creds, cache_discovery=False
            )
            # Query recent 30-day channel metrics
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            res = yt_analytics.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration",
                dimensions="day",
                sort="day"
            ).execute()

            rows = res.get("rows", [])
            total_views = sum(r[1] for r in rows) if rows else 0

            return {
                "authorized": True,
                "has_scope": True,
                "data_points": len(rows),
                "total_views_30d": total_views,
                "timing_source": "user_configured_studio",
                "message": (
                    f"Analytics active ({total_views} views in last 30 days). "
                    "Note: The YouTube Analytics API dimensions provide daily metrics. "
                    "Hourly audience peak times ('When your viewers are on YouTube') must be configured from your YouTube Studio heatmap."
                ) if total_views > 0 else "Not enough analytics data; using your manually selected publishing windows."
            }
        except Exception as exc:
            logger.warning("Error fetching YouTube Analytics: %s", exc)
            return {
                "authorized": True,
                "has_scope": True,
                "error": str(exc),
                "timing_source": "user_configured_studio",
                "message": "Not enough analytics data; using your manually selected publishing windows."
            }

    @classmethod
    def calculate_next_slots(cls, count: int = 4) -> List[Dict[str, Any]]:
        """Computes upcoming publication slots based on the twice-daily schedule."""
        cfg = cls.get_schedule_config()
        slot_1 = cfg.get("slot_1_time", "10:00")
        slot_2 = cfg.get("slot_2_time", "18:00")

        now = datetime.now(timezone.utc)
        slots = []

        for day_offset in range(7):
            day_date = (now + timedelta(days=day_offset)).date()
            for slot_label, s_time in [("slot_1", slot_1), ("slot_2", slot_2)]:
                try:
                    h, m = map(int, s_time.split(":"))
                except Exception:
                    h, m = 10, 0
                slot_dt = datetime(day_date.year, day_date.month, day_date.day, h, m, 0, tzinfo=timezone.utc)
                if slot_dt > now:
                    slots.append({
                        "slot_label": slot_label,
                        "time_str": s_time,
                        "datetime_utc": slot_dt.strftime("%Y-%m-%d %H:%M:%SZ"),
                        "datetime_iso": slot_dt.isoformat(),
                        "display": slot_dt.strftime("%b %d, %Y at %H:%M UTC")
                    })
                if len(slots) >= count:
                    return slots
        return slots

    @classmethod
    def queue_clip_for_scheduling(
        cls,
        clip_id: int,
        target_slot_datetime_utc: Optional[str] = None,
        destination_channel_id: Optional[str] = None,
        is_test: int = 0
    ) -> Dict[str, Any]:
        """
        Enqueues an approved rendered clip into youtube_scheduled_posts.
        Enforces:
        - Clip must be in 'rendered' status.
        - Same clip cannot be queued or published twice.
        - Enforces max 2 scheduled clips per day.
        """
        conn = get_db_connection()
        cur = conn.cursor()

        # Validate clip
        cur.execute("SELECT * FROM youtube_clips WHERE id = ?", (clip_id,))
        clip_row = cur.fetchone()
        if not clip_row:
            conn.close()
            return {"success": False, "error": f"Clip #{clip_id} not found."}

        clip = dict(clip_row)
        if clip.get("status") != "rendered" or not clip.get("output_path"):
            conn.close()
            return {"success": False, "error": f"Clip #{clip_id} is in status '{clip.get('status')}'; only successfully rendered clips can be scheduled."}

        # Idempotency check: is this clip already in the queue?
        cur.execute("SELECT id, status, scheduled_time FROM youtube_scheduled_posts WHERE clip_id = ?", (clip_id,))
        existing = cur.fetchone()
        if existing and existing["status"] in ("queued", "uploading", "scheduled_api", "published"):
            conn.close()
            return {
                "success": False,
                "error": f"Clip #{clip_id} is already {existing['status']} (Scheduled post #{existing['id']} at {existing['scheduled_time']})."
            }

        # Resolve slot time
        if not target_slot_datetime_utc:
            next_slots = cls.calculate_next_slots(count=1)
            if not next_slots:
                conn.close()
                return {"success": False, "error": "Could not calculate upcoming slot."}
            target_dt_str = next_slots[0]["datetime_utc"]
            slot_name = next_slots[0]["slot_label"]
        else:
            target_dt_str = target_slot_datetime_utc
            slot_name = "custom_slot"

        # Check max 2 posts per day constraint
        day_prefix = target_dt_str[:10]  # YYYY-MM-DD
        cur.execute("""
            SELECT COUNT(*) FROM youtube_scheduled_posts
            WHERE scheduled_time LIKE ? AND status IN ('queued', 'uploading', 'scheduled_api', 'published')
        """, (f"{day_prefix}%",))
        scheduled_count_today = cur.fetchone()[0]
        if scheduled_count_today >= 2:
            conn.close()
            return {
                "success": False,
                "error": f"Daily limit reached: {day_prefix} already has {scheduled_count_today} planned clips scheduled. MINT policy allows maximum 2 posts per day."
            }

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO youtube_scheduled_posts (
                clip_id, destination_channel_id, scheduled_time, target_slot,
                status, is_test, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
        """, (
            clip_id, destination_channel_id, target_dt_str, slot_name, is_test, now_str, now_str
        ))
        post_id = cur.lastrowid
        conn.commit()
        conn.close()

        return {
            "success": True,
            "scheduled_post_id": post_id,
            "clip_id": clip_id,
            "scheduled_time": target_dt_str,
            "status": "queued",
            "message": f"Clip #{clip_id} '{clip['clip_title']}' queued for publication at {target_dt_str}."
        }

    @classmethod
    def list_scheduled_posts(cls, limit: int = 50, include_test: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        q = """
            SELECT sp.*, c.clip_title, c.duration_sec, c.output_path, c.hashtags
            FROM youtube_scheduled_posts sp
            JOIN youtube_clips c ON sp.clip_id = c.id
        """
        params = []
        if not include_test:
            q += " WHERE sp.is_test = 0"
        q += " ORDER BY sp.id DESC LIMIT ?"
        params.append(limit)

        cur.execute(q, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @classmethod
    def cancel_scheduled_post(cls, post_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_scheduled_posts WHERE id = ?", (post_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"Scheduled post #{post_id} not found."}

        p = dict(row)
        if p["status"] == "published":
            conn.close()
            return {"success": False, "error": "Cannot cancel a post that has already been published to YouTube."}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE youtube_scheduled_posts SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_str, post_id))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Scheduled post #{post_id} has been cancelled."}

    @classmethod
    def publish_scheduled_post(cls, post_id: int, confirmed: bool = False) -> Dict[str, Any]:
        """
        Uploads the clip via YouTube Data API with status.publishAt set to the scheduled time.
        In YouTube Data API, specifying status.publishAt requires status.privacyStatus='private'.
        """
        if not confirmed:
            return {"success": False, "error": "Publishing requires explicit user confirmation (confirmed=true)."}

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT sp.*, c.clip_title, c.clip_description, c.hashtags, c.output_path
            FROM youtube_scheduled_posts sp
            JOIN youtube_clips c ON sp.clip_id = c.id
            WHERE sp.id = ?
        """, (post_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"Scheduled post #{post_id} not found."}

        p = dict(row)
        if p["status"] in ("published", "scheduled_api"):
            conn.close()
            return {"success": False, "error": f"Post #{post_id} is already in state '{p['status']}'."}

        clip_path = Path(p["output_path"]).resolve()
        if not clip_path.exists() or not clip_path.is_file():
            conn.close()
            return {"success": False, "error": f"Clip file not found: {p['output_path']}"}

        # Check for OAuth credentials
        creds = _load_token("youtube")
        if not creds:
            conn.close()
            return {"success": False, "error": "YouTube OAuth is not connected. Authorize YouTube first."}

        # Mark as uploading to lock the row against duplicate workers
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE youtube_scheduled_posts SET status = 'uploading', attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?", (now_str, post_id))
        conn.commit()

        # Parse target publish time to ISO RFC 3339 format
        sched_time_str = p["scheduled_time"]
        try:
            # Format to RFC 3339 UTC
            clean_str = sched_time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            publish_at_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            publish_at_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # YouTube Data API call
        try:
            creds = _refresh_if_needed(creds)
            yt = _build_youtube_client(creds)

            tags = [t.strip("#").strip() for t in (p.get("hashtags") or "").split() if t.strip()]
            if not tags:
                tags = ["shorts", "automation", "mint"]

            metadata = {
                "snippet": {
                    "title": p["clip_title"][:100],
                    "description": (p["clip_description"] or "")[:5000],
                    "tags": tags[:20],
                    "categoryId": "28",  # Science & Technology
                },
                "status": {
                    "privacyStatus": "private",  # Mandatory when publishAt is specified
                    "publishAt": publish_at_iso,
                    "selfDeclaredMadeForKids": False,
                }
            }

            media = googleapiclient.http.MediaFileUpload(
                str(clip_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024 * 5
            )

            insert_request = yt.videos().insert(
                part="snippet,status",
                body=metadata,
                media_body=media
            )

            response = None
            while response is None:
                status, response = insert_request.next_chunk()

            video_id = response.get("id")
            returned_status = response.get("status", {})
            returned_publish_at = returned_status.get("publishAt") or publish_at_iso
            video_url = f"https://youtu.be/{video_id}" if video_id else None

            cur.execute("""
                UPDATE youtube_scheduled_posts
                SET status = 'scheduled_api', youtube_video_id = ?, youtube_video_url = ?,
                    publish_at_iso = ?, published_at = ?, error_message = NULL, updated_at = ?
                WHERE id = ?
            """, (video_id, video_url, returned_publish_at, now_str, now_str, post_id))
            conn.commit()
            conn.close()

            return {
                "success": True,
                "status": "scheduled_api",
                "post_id": post_id,
                "video_id": video_id,
                "video_url": video_url,
                "publish_at": returned_publish_at,
                "message": f"Successfully uploaded to YouTube. Scheduled to go public at {returned_publish_at}."
            }

        except googleapiclient.errors.HttpError as exc:
            err_msg = f"YouTube API error: {exc.reason}"
            cur.execute("UPDATE youtube_scheduled_posts SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?", (err_msg, now_str, post_id))
            conn.commit()
            conn.close()
            return {"success": False, "error": err_msg}
        except Exception as exc:
            err_msg = f"Upload error: {str(exc)}"
            cur.execute("UPDATE youtube_scheduled_posts SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?", (err_msg, now_str, post_id))
            conn.commit()
            conn.close()
            return {"success": False, "error": err_msg}

    @classmethod
    def check_and_process_missed_slots(cls) -> Dict[str, Any]:
        """
        Offline gap detection:
        Identifies queued posts whose scheduled publication slot has passed while MINT was offline.
        Marks them 'missed' to avoid bursting old posts on startup, and flags that scheduler should queue upcoming slots.
        """
        now = datetime.now(timezone.utc)
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id, scheduled_time, clip_id FROM youtube_scheduled_posts WHERE status = 'queued'")
        queued = cur.fetchall()

        missed_count = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for q in queued:
            sched_str = q["scheduled_time"]
            try:
                clean_str = sched_str.replace("Z", "+00:00")
                sched_dt = datetime.fromisoformat(clean_str)
                if sched_dt.tzinfo is None:
                    sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                if sched_dt < now:
                    cur.execute("""
                        UPDATE youtube_scheduled_posts
                        SET status = 'missed', error_message = 'Scheduled slot passed while MINT was offline; marked missed to prevent upload burst.', updated_at = ?
                        WHERE id = ?
                    """, (now_str, q["id"]))
                    missed_count += 1
            except Exception:
                pass

        conn.commit()
        conn.close()
        return {"checked": len(queued), "missed_marked": missed_count}

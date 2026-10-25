"""
services/social_service.py
YouTube and Instagram platform connectors for MINT.

YouTubeService:
  - Reads OAuth tokens from oauth_tokens table (set by routes/youtube_auth.py)
  - Fetches real channel info via YouTube Data API v3
  - Caches channel info for 5 minutes to avoid quota waste

InstagramService:
  - Uses Meta Graph API to verify account and permissions
  - Returns detailed status: not_configured | token_invalid | connected_no_publish |
    connected | publishing | published | failed
  - Never claims connected/ready based only on env var presence
"""

import os
import json
import time
import logging
import hashlib
import re
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ── Simple in-process cache (avoids hitting API every 3s poll) ────────────────
_yt_channel_cache: Dict[str, Any] = {}
_yt_channel_cache_time: float = 0.0
_YT_CACHE_TTL = 300  # 5 minutes

_ig_status_cache: Dict[str, Any] = {}
_ig_status_cache_time: float = 0.0
_ig_status_cache_key: str = ""
_IG_CACHE_TTL = 60  # 1 minute


class YouTubeService:
    """
    YouTube Data API v3 connector.
    Reads stored OAuth credentials from the oauth_tokens table.
    Credentials are set via the web OAuth flow at /auth/youtube.
    """

    @classmethod
    def _load_creds(cls):
        """Load stored credentials. Returns (creds_obj | None, error_str | None)."""
        try:
            from database import get_db_connection
            import google.oauth2.credentials
            import google.auth.transport.requests

            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT token_json FROM oauth_tokens WHERE provider = 'youtube'"
                ).fetchone()

            if not row:
                return None, "not_connected"

            data = json.loads(row["token_json"])
            creds = google.oauth2.credentials.Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                scopes=data.get("scopes"),
            )

            if (creds.expired or not creds.token) and creds.refresh_token:
                creds.refresh(google.auth.transport.requests.Request())
                # Persist refreshed token
                refreshed = {
                    "token":         creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri":     creds.token_uri,
                    "client_id":     creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes":        list(creds.scopes) if creds.scopes else [],
                }
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE oauth_tokens SET token_json=?, updated_at=datetime('now') WHERE provider='youtube'",
                        (json.dumps(refreshed),)
                    )
                    conn.commit()

            return creds, None

        except Exception as exc:
            logger.exception("YouTubeService._load_creds failed")
            return None, str(exc)

    @classmethod
    def get_channel_info(cls, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Fetch channel info from YouTube API. Cached for 5 minutes.
        Returns channel dict or error dict. Never fabricates data.
        """
        global _yt_channel_cache, _yt_channel_cache_time

        now = time.time()
        if not force_refresh and _yt_channel_cache and (now - _yt_channel_cache_time) < _YT_CACHE_TTL:
            return dict(_yt_channel_cache, cache_hit=True)

        creds, err = cls._load_creds()
        if err:
            return {"ok": False, "error": err, "cache_hit": False}

        try:
            import googleapiclient.discovery
            import googleapiclient.errors
            yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds, cache_discovery=False)
            resp = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
            items = resp.get("items", [])
            if not items:
                result = {"ok": False, "error": "No YouTube channel found for this account.", "cache_hit": False}
                return result
            ch = items[0]
            snippet = ch.get("snippet", {})
            stats = ch.get("statistics", {})

            # Fetch recent videos from channel's uploads playlist (lowest quota: 1 unit)
            recent_videos = []
            uploads_playlist = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if uploads_playlist:
                try:
                    pl_resp = yt.playlistItems().list(
                        part="snippet,status",
                        playlistId=uploads_playlist,
                        maxResults=5
                    ).execute()
                    for item in pl_resp.get("items", []):
                        snip = item.get("snippet", {})
                        stat = item.get("status", {})
                        vid_id = snip.get("resourceId", {}).get("videoId")
                        if vid_id:
                            recent_videos.append({
                                "video_id": vid_id,
                                "title": snip.get("title", "Untitled"),
                                "published_at": snip.get("publishedAt", ""),
                                "privacy_status": stat.get("privacyStatus", "private"),
                                "url": f"https://youtu.be/{vid_id}",
                            })
                except Exception as pl_err:
                    logger.debug("Could not fetch uploads playlist: %s", pl_err)

            result = {
                "ok": True,
                "channel_id": ch.get("id"),
                "channel_name": snippet.get("title"),
                "custom_url": snippet.get("customUrl"),
                "description": (snippet.get("description") or "")[:200],
                "subscriber_count": stats.get("subscriberCount"),
                "video_count": stats.get("videoCount"),
                "view_count": stats.get("viewCount"),
                "recent_videos": recent_videos,
                "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "cache_hit": False,
            }
            _yt_channel_cache = result
            _yt_channel_cache_time = now
            return result
        except Exception as exc:
            logger.warning("YouTubeService.get_channel_info failed: %s", exc)
            return {"ok": False, "error": str(exc), "cache_hit": False}

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        creds, err = cls._load_creds()

        if err == "not_connected":
            return {
                "configured": False,
                "connected": False,
                "status": "not_connected",
                "message": (
                    "YouTube account not connected. "
                    "Visit the dashboard and click 'Connect YouTube' to authorize."
                ),
                "channel_name": None,
                "can_upload": False,
            }

        if err:
            return {
                "configured": True,
                "connected": False,
                "status": "token_error",
                "message": f"Stored token error: {err}. Reconnect to fix.",
                "can_upload": False,
            }

        has_upload_scope = "https://www.googleapis.com/auth/youtube.upload" in set(creds.scopes or [])
        return {
            "configured": True,
            "connected": True,
            "status": "connected" if has_upload_scope else "needs_permissions",
            "message": (
                "YouTube account connected with upload permission."
                if has_upload_scope
                else "Connected but youtube.upload scope not granted. Reconnect."
            ),
            "can_upload": has_upload_scope,
        }

    @classmethod
    def get_upload_history(cls) -> list:
        """
        Returns MINT-recorded YouTube uploads (from activity_log), not YouTube analytics.
        We only know what we uploaded; viewer stats require YouTube Analytics API.
        """
        try:
            from database import get_db_connection
            with get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT description, created_at FROM activity_log "
                    "WHERE event_type = 'youtube_upload' ORDER BY id DESC LIMIT 10"
                ).fetchall()
            return [{"description": r["description"], "uploaded_at": r["created_at"]} for r in rows]
        except Exception:
            return []

    @classmethod
    def upload_video(
        cls,
        video_path: str,
        title: str,
        description: str,
        tags: list = None,
    ) -> Dict[str, Any]:
        """
        Upload a video file as private. Returns success dict with video_id and URL,
        or export_ready dict if not connected.
        NOTE: private != public. Never mark published=True for private uploads.
        """
        cls._reload_env_if_needed(force=True)
        status = cls.get_status(force_refresh=True)
        if not status.get("can_upload"):
            return {
                "success": False,
                "error": status["message"],
                "export_ready": True,
                "file_path": video_path,
                "metadata": {
                    "title":       title,
                    "description": description,
                    "tags":        tags or ["mint", "entrepreneurship", "automation"],
                },
            }

        creds, err = cls._load_creds()
        if err:
            return {"success": False, "error": err}

        try:
            import googleapiclient.discovery
            import googleapiclient.http
            import googleapiclient.errors

            yt = googleapiclient.discovery.build(
                "youtube", "v3", credentials=creds, cache_discovery=False
            )
            metadata = {
                "snippet": {
                    "title":       (title or "MINT Generated Video")[:100],
                    "description": (description or "")[:5000],
                    "tags":        tags or ["mint", "indie", "digitalventure"],
                    "categoryId":  "28",
                },
                "status": {
                    "privacyStatus": "private",   # Always private — never public by default
                    "selfDeclaredMadeForKids": False,
                },
            }
            media = googleapiclient.http.MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024 * 5,
            )
            insert_req = yt.videos().insert(
                part="snippet,status",
                body=metadata,
                media_body=media,
            )
            response = None
            while response is None:
                _, response = insert_req.next_chunk()

            vid_id = response.get("id")
            # Invalidate channel cache so video_count updates
            global _yt_channel_cache_time
            _yt_channel_cache_time = 0.0
            return {
                "success": True,
                "video_id": vid_id,
                "url": f"https://youtu.be/{vid_id}" if vid_id else None,
                "privacy": "private",
                "published": False,  # private ≠ public; never mark True here
                "note": "Uploaded as private. Use YouTube Studio to publish publicly.",
            }

        except Exception as exc:
            logger.exception("YouTubeService.upload_video failed")
            return {"success": False, "error": str(exc)}


class InstagramService:
    """
    Official Meta Graph API connector for Instagram Business & Creator accounts.
    Requires a Facebook Page-connected Instagram Business or Creator account.

    Status levels:
      not_configured        — env vars missing
      token_invalid         — token exists but API rejected it
      connected_no_publish  — token valid but publish permissions missing
      connected             — ready to publish (has instagram_content_publish)
      publishing            — media container processing
      published             — successfully published
      failed                — API error
      media_hosting_required — local file path given; Meta needs public HTTPS URL
    """

    @classmethod
    def _reload_env_if_needed(cls, force: bool = False):
        import sys
        if any(m in sys.modules for m in ["unittest", "pytest"]):
            return
        try:
            from dotenv import load_dotenv
            env_file = Path(__file__).resolve().parent.parent / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=force)
        except Exception:
            pass

    @classmethod
    def get_login_method(cls) -> str:
        """Resolve the explicitly selected Meta login flow. Auto-detects Facebook/Meta token format."""
        cls._reload_env_if_needed()
        raw = os.getenv("INSTAGRAM_LOGIN_METHOD", "").strip().lower().replace("-", "_")
        if raw in {"facebook", "facebook_login", "fb_login", "facebook_login_for_business"}:
            return "facebook_login"
        if raw in {"instagram", "instagram_login", "ig_login", "business_login_for_instagram"}:
            token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
            # EAA... tokens are Facebook Graph API / System User tokens and will always fail on graph.instagram.com
            if token.startswith("EAA"):
                return "facebook_login"
            return "instagram_login"
        # If not specified, infer from token prefix
        token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        if token.startswith("EAA"):
            return "facebook_login"
        return "instagram_login"

    @classmethod
    def get_api_version(cls) -> str:
        """Return a safe, explicitly versioned Meta Graph API version."""
        import re
        version = os.getenv("META_GRAPH_API_VERSION", "v26.0").strip()
        return version if re.fullmatch(r"v\d+\.0", version) else "v26.0"

    @classmethod
    def get_graph_base_url(cls) -> str:
        """Instagram Login and Facebook Login use different Graph API hosts."""
        return "https://graph.instagram.com" if cls.get_login_method() == "instagram_login" else "https://graph.facebook.com"

    @classmethod
    def _check_token(cls, ig_user_id: str, access_token: str) -> Dict[str, Any]:
        """Verify a token against the profile endpoint for the selected login flow."""
        method = cls.get_login_method()
        version = cls.get_api_version()
        if method == "instagram_login":
            endpoint = f"https://graph.instagram.com/{version}/me"
            fields = "user_id,username,account_type"
        elif method == "facebook_login":
            if not ig_user_id:
                return {"ok": False, "error_message": "Facebook Login requires INSTAGRAM_ACCOUNT_ID."}
            endpoint = f"https://graph.facebook.com/{version}/{ig_user_id}"
            # Instagram Business Accounts support id,name,username.
            fields = "id,name,username"
        else:
            return {"ok": False, "error_message": "Invalid INSTAGRAM_LOGIN_METHOD. Use instagram_login or facebook_login."}

        try:
            res = requests.get(
                endpoint,
                params={"fields": fields},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=(3, 8),
            )
            try:
                payload = res.json()
            except ValueError:
                payload = {}
            if res.ok and not payload.get("error"):
                return {"ok": True, "data": payload}
            err_data = payload.get("error", {}) if isinstance(payload, dict) else {}
            return {
                "ok": False,
                "http_status": res.status_code,
                "error_code": err_data.get("code"),
                "error_type": err_data.get("type"),
                "error_message": err_data.get("message", f"Meta returned HTTP {res.status_code} without a readable error."),
            }
        except requests.exceptions.Timeout:
            return {"ok": False, "error_message": "Meta profile check timed out. Try again."}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error_message": "Network unavailable; MINT could not reach Meta."}
        except Exception as exc:
            logger.warning("Instagram profile check failed: %s", type(exc).__name__)
            return {"ok": False, "error_message": "Unexpected error while checking the Instagram profile."}

    @classmethod
    def _check_permissions(cls, access_token: str) -> Dict[str, Any]:
        """For Facebook Login, ask Meta which permissions this token actually has."""
        if cls.get_login_method() != "facebook_login":
            return {"ok": False, "error_message": "Permission introspection endpoint is used only for Facebook Login."}
        endpoint = f"https://graph.facebook.com/{cls.get_api_version()}/me/permissions"
        try:
            res = requests.get(
                endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=(3, 8),
            )
            try:
                payload = res.json()
            except ValueError:
                payload = {}
            if not res.ok or not isinstance(payload, dict) or payload.get("error"):
                err = payload.get("error", {}) if isinstance(payload, dict) else {}
                message = str(err.get("message") or f"Meta returned HTTP {res.status_code} for permission introspection.")
                message = message.replace(access_token, "[redacted]") if access_token else message
                return {"ok": False, "error_code": err.get("code"), "error_message": message}
            permissions = {}
            for item in payload.get("data", []):
                if isinstance(item, dict) and item.get("permission"):
                    permissions[str(item["permission"]).lower()] = str(item.get("status", "")).lower()
            return {"ok": True, "permissions": permissions}
        except requests.exceptions.Timeout:
            return {"ok": False, "error_message": "Meta permission check timed out."}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error_message": "Network unavailable during Meta permission check."}
        except Exception as exc:
            logger.warning("Instagram permission check failed: %s", type(exc).__name__)
            return {"ok": False, "error_message": "Unexpected error checking Meta permissions."}

    @classmethod
    def get_status(cls, force_refresh: bool = False) -> Dict[str, Any]:
        global _ig_status_cache, _ig_status_cache_time, _ig_status_cache_key

        if force_refresh:
            cls._reload_env_if_needed(force=True)
            _ig_status_cache = None
            _ig_status_cache_time = 0
            _ig_status_cache_key = None

        now = time.time()
        method = cls.get_login_method()
        ig_user_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        granted_scopes_raw = os.getenv("INSTAGRAM_GRANTED_SCOPES", "")
        granted_scopes = {
            scope.strip().lower()
            for scope in re.split(r"[,;\s]+", granted_scopes_raw)
            if scope.strip()
        }
        required_scope = (
            "instagram_business_content_publish"
            if method == "instagram_login"
            else "instagram_content_publish"
        )
        # Cache keys are one-way digests. The access token itself is never stored in a cache key.
        token_digest = hashlib.sha256(access_token.encode("utf-8")).hexdigest() if access_token else ""
        cache_key = hashlib.sha256(
            f"{method}|{ig_user_id}|{token_digest}|{sorted(granted_scopes)}".encode("utf-8")
        ).hexdigest()

        def finish(result: Dict[str, Any]) -> Dict[str, Any]:
            global _ig_status_cache, _ig_status_cache_time, _ig_status_cache_key
            _ig_status_cache = dict(result)
            _ig_status_cache_time = time.time()
            _ig_status_cache_key = cache_key
            return dict(result, cache_hit=False)

        if not force_refresh and _ig_status_cache and cache_key == _ig_status_cache_key and (now - _ig_status_cache_time) < _IG_CACHE_TTL:
            return dict(_ig_status_cache, cache_hit=True)

        if method == "invalid":
            return finish({
                "configured": False,
                "status": "configuration_error",
                "can_publish": False,
                "login_method": "invalid",
                "message": "INSTAGRAM_LOGIN_METHOD must be instagram_login or facebook_login.",
                "setup_required": ["Set INSTAGRAM_LOGIN_METHOD=instagram_login for Business Login for Instagram, or facebook_login for Facebook Login for Business."],
            })

        missing = []
        if not access_token:
            missing.append("INSTAGRAM_ACCESS_TOKEN")
        if method == "facebook_login" and not ig_user_id:
            missing.append("INSTAGRAM_ACCOUNT_ID")
        if missing:
            return finish({
                "configured": False,
                "status": "not_configured",
                "can_publish": False,
                "login_method": method,
                "message": f"Instagram credentials are missing: {', '.join(missing)}.",
                "setup_required": [
                    "For Instagram Login, use an Instagram professional account and an Instagram User access token.",
                    "For Facebook Login, use a Facebook Page-connected Instagram professional account and Page access token.",
                    f"Grant the publishing permission {required_scope}.",
                    "Set INSTAGRAM_ACCOUNT_ID and INSTAGRAM_ACCESS_TOKEN as required by the selected login method.",
                ],
            })

        check = cls._check_token(ig_user_id, access_token)
        if not check.get("ok"):
            err_code = check.get("error_code")
            err_msg = str(check.get("error_message") or "Meta did not provide an error description.")
            err_msg = err_msg.replace(access_token, "[redacted]") if access_token else err_msg
            from services.media_hosting_service import MediaHostingService
            hosting = MediaHostingService.get_status()

            if err_code == 190:
                status = "token_invalid"
                msg = "Instagram access token was rejected or has expired. Generate a fresh token in Meta App Dashboard / Graph API Explorer."
                setup_steps = [
                    "Regenerate your User / Page Access Token in Graph API Explorer or Meta App Dashboard.",
                    "Ensure the token has not expired."
                ]
            elif err_code == 200:
                status = "permission_error"
                msg = "Meta Graph API Error 200: API access blocked or unsupported object request. Your Meta Developer App is in Development Mode or has restricted API access."
                setup_steps = [
                    "Root cause: Meta App is in Development Mode or the target account is not assigned to App Roles.",
                    "Fix 1: In Meta Developer Dashboard (developers.facebook.com), switch App Mode from 'Development' to 'Live'.",
                    "Fix 2: If keeping Development Mode, go to App Roles -> Roles and add your Facebook User / Instagram account as a Tester or Developer.",
                    f"Fix 3: Confirm your token has granted scopes: {required_scope}, instagram_basic, pages_show_list.",
                    "Fix 4: Confirm INSTAGRAM_ACCOUNT_ID is your Instagram Business Account ID and not your personal Facebook User ID.",
                    f"Media Hosting check: {'Ready (Cloudinary)' if hosting.get('configured') else 'Needs configuration (Cloudinary)'}."
                ]
            elif err_code in (10, 203):
                status = "permission_error"
                msg = f"Meta denied this request (code {err_code}). Check the selected login flow and granted permissions."
                setup_steps = [
                    f"Confirm the account has granted {required_scope}.",
                    "Check token permissions in Meta Access Token Debugger."
                ]
            else:
                status = "connection_error"
                msg = f"Meta profile check failed: {err_msg}"
                setup_steps = [
                    f"Confirm the token was generated for {method}.",
                    f"Confirm the account has granted {required_scope}.",
                    "Use Check Connection to retry after changing credentials."
                ]
            return finish({
                "configured": True,
                "status": status,
                "can_publish": False,
                "login_method": method,
                "message": msg,
                "error_code": err_code,
                "http_status": check.get("http_status"),
                "required_publish_scope": required_scope,
                "setup_required": setup_steps,
                "media_hosting": hosting
            })

        account_data = check["data"]
        account_type = str(account_data.get("account_type") or ("PROFESSIONAL" if method == "facebook_login" else "unknown")).upper()
        username = str(account_data.get("username") or "").strip()
        display_name = str(account_data.get("name") or "").strip()
        account_label = f"@{username}" if username else (display_name or "Instagram account")
        verified_id = str(
            account_data.get("user_id")
            or account_data.get("id")
            or ig_user_id
        ).strip()

        if account_type not in {"BUSINESS", "CREATOR", "MEDIA_CREATOR", "PROFESSIONAL"}:
            return finish({
                "configured": True,
                "status": "unsupported_account",
                "can_publish": False,
                "account_verified": True,
                "login_method": method,
                "username": username,
                "account_type": account_type,
                "account_id": verified_id,
                "message": f"Meta verified the account profile, but its account type is {account_type}. Instagram publishing requires a professional Business or Creator account.",
                "required_publish_scope": required_scope,
                "setup_required": ["Switch the Instagram account to Business or Creator in Instagram settings, then re-check the connection."],
            })

        permission_verified = False
        permission_source = "user_declared_granted_scopes"
        if method == "facebook_login":
            # The Facebook Login token supports direct permission introspection.
            permission_check = cls._check_permissions(access_token)
            if not permission_check.get("ok"):
                return finish({
                    "configured": True,
                    "status": "permission_check_error",
                    "can_publish": False,
                    "account_verified": True,
                    "permission_verified": False,
                    "login_method": method,
                    "api_version": cls.get_api_version(),
                    "username": username,
                    "account_type": account_type,
                    "account_id": verified_id,
                    "required_publish_scope": required_scope,
                    "message": f"Account verified as @{username}, but Meta permission status could not be confirmed: {permission_check.get('error_message', 'unknown permission check error')}",
                    "setup_required": ["Retry Check Connection.", "If this persists, check the token in Meta's Access Token Debugger."],
                })
            permission_verified = permission_check.get("permissions", {}).get(required_scope) == "granted"
            permission_source = "meta_me_permissions"
            if not permission_verified:
                return finish({
                    "configured": True,
                    "status": "connected_no_publish",
                    "can_publish": False,
                    "account_verified": True,
                    "permission_verified": True,
                    "login_method": method,
                    "api_version": cls.get_api_version(),
                    "username": username,
                    "account_type": account_type,
                    "account_id": verified_id,
                    "required_publish_scope": required_scope,
                    "message": f"Account verified as @{username}, but Meta does not report {required_scope} as granted for this token.",
                    "setup_required": [f"Grant {required_scope} in the Meta app, then re-authorize or refresh the token and check again."],
                })
        else:
            # Instagram Login profile responses do not enumerate consent scopes. Require
            # the user to record the scopes that were confirmed in Meta before enabling publish.
            scope_declared = required_scope in granted_scopes
            if not scope_declared:
                return finish({
                    "configured": True,
                    "status": "connected_no_publish",
                    "can_publish": False,
                    "account_verified": True,
                    "permission_verified": False,
                    "login_method": method,
                    "api_version": cls.get_api_version(),
                    "username": username,
                    "account_type": account_type,
                    "account_id": verified_id,
                    "required_publish_scope": required_scope,
                    "message": f"Account verified as @{username}. MINT cannot infer the token's granted publishing scopes from a profile request. After confirming the Meta grant, add {required_scope} to INSTAGRAM_GRANTED_SCOPES and click Check Connection.",
                    "setup_required": [
                        f"Verify that the token grant includes {required_scope}.",
                        f"Set INSTAGRAM_GRANTED_SCOPES={required_scope} (Instagram Login normally also needs instagram_business_basic).",
                        "Click Check Connection again.",
                    ],
                    "note": "Media must be hosted at a publicly accessible HTTPS URL before Meta can fetch it.",
                })

        return finish({
            "configured": True,
            "status": "connected",
            "can_publish": True,
            "account_verified": True,
            "permission_verified": permission_verified,
            "permission_source": permission_source,
            "login_method": method,
            "api_version": cls.get_api_version(),
            "username": username or None,
            "display_name": display_name or None,
            "account_label": account_label,
            "account_type": account_type,
            "account_id": verified_id,
            "required_publish_scope": required_scope,
            "message": f"Connected to {account_label} ({account_type}). " + ("Meta confirmed the required publishing permission." if permission_verified else "The publishing scope was declared in MINT configuration; Meta will revalidate permissions during publishing."),
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "Media must be at a publicly accessible HTTPS URL for Meta to fetch it. Local files and localhost URLs cannot be published directly.",
        })

    @classmethod
    def get_detailed_diagnostics(cls) -> Dict[str, Any]:
        """
        Comprehensive 10-point diagnostic check of Instagram API connectivity,
        Meta App Mode, token validation, account type, and media hosting.
        """
        from services.media_hosting_service import MediaHostingService

        hosting_status = MediaHostingService.get_status()
        status = cls.get_status(force_refresh=True)

        account_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()

        diag_checks = [
            {
                "name": "Environment Credentials",
                "passed": bool(account_id and access_token),
                "details": f"INSTAGRAM_ACCOUNT_ID: {'Present' if account_id else 'Missing'}, Token: {'Present' if access_token else 'Missing'}"
            },
            {
                "name": "Login Method",
                "passed": cls.get_login_method() in ("facebook_login", "instagram_login"),
                "details": f"Configured as {cls.get_login_method()}"
            },
            {
                "name": "Token Validity",
                "passed": status.get("status") not in ("not_configured", "token_invalid"),
                "details": status.get("message", "Token verified")
            },
            {
                "name": "Meta API Reachability",
                "passed": status.get("status") != "connection_error",
                "details": f"Target endpoint: {cls.get_graph_base_url()}/{cls.get_api_version()}"
            },
            {
                "name": "Meta App Mode (Code 200 Check)",
                "passed": status.get("error_code") != 200,
                "details": "Meta App check passed" if status.get("error_code") != 200 else "Code 200: Meta App in Development Mode or missing App Roles / scopes."
            },
            {
                "name": "Account Professional Status",
                "passed": status.get("account_verified", False) or status.get("account_type") in ("BUSINESS", "CREATOR"),
                "details": f"Type: {status.get('account_type', 'Unverified')}"
            },
            {
                "name": "Publishing Scope",
                "passed": status.get("can_publish", False),
                "details": f"Scope required: {status.get('required_publish_scope', 'instagram_content_publish')}"
            },
            {
                "name": "Public HTTPS Media Hosting",
                "passed": hosting_status.get("configured", False),
                "details": hosting_status.get("message", "")
            }
        ]

        return {
            "success": True,
            "overall_status": status.get("status"),
            "can_publish": status.get("can_publish", False),
            "account_label": status.get("username") or status.get("account_id") or "Instagram Account",
            "error_code": status.get("error_code"),
            "error_message": status.get("message"),
            "actionable_guidance": status.get("setup_required", []),
            "checks": diag_checks,
            "media_hosting": hosting_status
        }

    @classmethod
    def publish_media(
        cls,
        media_url_or_path: str,
        caption: str,
        media_type: str = "REELS",
        confirmed: bool = False
    ) -> Dict[str, Any]:
        """
        Publishes media to Instagram Business/Creator account using official Meta Graph API:
          Step 1: POST /{ig_user_id}/media (create container)
          Step 2: GET /{container_id}?fields=status_code (poll until FINISHED for video)
          Step 3: POST /{ig_user_id}/media_publish (publish container)

        Requirements:
          1. confirmed=True (explicit user consent required)
          2. Media at public HTTPS URL (Meta cannot fetch from localhost or local disk)
        """
        if not confirmed:
            return {
                "success": False,
                "status": "confirmation_required",
                "error": "Publishing to Instagram requires explicit confirmation. Set confirmed=True.",
            }

        # Check media hosting first: Meta Graph API cannot download local files under any circumstance
        is_local = (
            not media_url_or_path.lower().startswith("https://")
            or "127.0.0.1" in media_url_or_path.lower()
            or "localhost" in media_url_or_path.lower()
            or ".local/" in media_url_or_path.lower()
        )

        if is_local:
            return {
                "success": False,
                "status": "media_hosting_required",
                "error": (
                    "Meta Graph API requires a publicly accessible HTTPS URL. "
                    "Local files (127.0.0.1 or local paths) cannot be fetched by Meta's servers. "
                    "Host your media at a public URL first (e.g., CDN, cloud storage)."
                ),
                "export_ready": True,
                "file_path": media_url_or_path,
                "caption": caption,
            }

        cls._reload_env_if_needed(force=True)
        status = cls.get_status(force_refresh=True)
        if not status.get("can_publish"):
            return {
                "success": False,
                "status": status.get("status", "not_configured"),
                "error": status.get("message", "Instagram account not connected or missing permissions."),
                "file_path": media_url_or_path,
                "caption": caption,
            }

        ig_user_id = str(status.get("account_id") or os.getenv("INSTAGRAM_ACCOUNT_ID", "")).strip()
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        api_version = cls.get_api_version()
        graph_base_url = cls.get_graph_base_url()
        auth_headers = {"Authorization": f"Bearer {access_token}"}
        if not ig_user_id:
            return {"success": False, "status": "not_configured", "error": "Instagram account ID is unavailable from the verified profile."}

        try:
            # Step 1: Create media container using the host for the selected login flow.
            container_url = f"{graph_base_url}/{api_version}/{ig_user_id}/media"
            container_payload = {"caption": caption[:2200]}
            if media_type == "REELS":
                container_payload["media_type"] = "REELS"
                container_payload["video_url"] = media_url_or_path
            else:
                container_payload["image_url"] = media_url_or_path

            res = requests.post(container_url, data=container_payload, headers=auth_headers, timeout=(3, 20))
            if res.status_code != 200:
                try:
                    err_json = res.json().get("error", {})
                except Exception:
                    err_json = {}
                err = err_json.get("message", res.text)
                subcode = err_json.get("error_subcode")
                if subcode == 33 or "Unsupported post request" in str(err) or "does not support this operation" in str(err):
                    err = (
                        f"Meta rejected target account ID '{ig_user_id}'. "
                        "Meta Graph API requires an Instagram Professional/Business Account ID (a numeric ID starting with 1784...), "
                        "not a Facebook User ID. In Meta Business Suite (business.facebook.com), go to System Users > 'srish' > Add Assets, "
                        "assign your Instagram account, and set INSTAGRAM_ACCOUNT_ID to that Instagram Account ID in .env."
                    )
                return {
                    "success": False,
                    "status": "failed",
                    "error": f"Meta container creation failed: {err}",
                }

            container_id = res.json().get("id")
            if not container_id:
                return {"success": False, "status": "failed", "error": "No container ID returned by Meta API."}

            # Step 2: Poll container status (for video/reels)
            if media_type == "REELS":
                import time as _time
                status_url = f"{graph_base_url}/{api_version}/{container_id}"
                ready = False
                for _ in range(6):
                    _time.sleep(5)
                    st_res = requests.get(
                        status_url,
                        params={"fields": "status_code"},
                        headers=auth_headers,
                        timeout=(3, 10),
                    )
                    if st_res.status_code == 200:
                        code = st_res.json().get("status_code")
                        if code == "FINISHED":
                            ready = True
                            break
                        elif code == "ERROR":
                            return {"success": False, "status": "failed", "error": "Meta container processing failed on server."}
                if not ready:
                    return {
                        "success": False,
                        "status": "publishing",
                        "container_id": container_id,
                        "message": "Video is still processing on Meta servers. Try publishing the container_id manually once ready.",
                    }

            # Step 3: Publish container
            publish_url = f"{graph_base_url}/{api_version}/{ig_user_id}/media_publish"
            pub_res = requests.post(
                publish_url,
                data={"creation_id": container_id},
                headers=auth_headers,
                timeout=(3, 20),
            )
            if pub_res.status_code == 200:
                media_id = pub_res.json().get("id")
                # Invalidate Instagram status cache
                global _ig_status_cache_time, _ig_status_cache_key
                _ig_status_cache_time = 0.0
                _ig_status_cache_key = ""
                return {
                    "success": True,
                    "status": "published",
                    "media_id": media_id,
                    "published": True,
                }
            else:
                err = pub_res.json().get("error", {}).get("message", pub_res.text)
                return {"success": False, "status": "failed", "error": f"Meta publishing failed: {err}"}

        except Exception as exc:
            logger.exception("InstagramService.publish_media failed")
            return {"success": False, "status": "failed", "error": str(exc)}

    @classmethod
    def publish_carousel(
        cls,
        image_urls: list,
        caption: str,
        confirmed: bool = False
    ) -> Dict[str, Any]:
        """
        Publishes a multi-image carousel to Instagram using official Meta Graph API:
          Step 1: POST /{ig_user_id}/media (create child container for each image with is_carousel_item=true)
          Step 2: POST /{ig_user_id}/media (create parent container with media_type=CAROUSEL, children=[ids...])
          Step 3: POST /{ig_user_id}/media_publish (publish parent container)
        """
        if not confirmed:
            return {
                "success": False,
                "status": "confirmation_required",
                "error": "Publishing carousel requires explicit confirmation. Set confirmed=True.",
            }

        if not image_urls or len(image_urls) < 2:
            return {
                "success": False,
                "status": "validation_error",
                "error": "A carousel post requires at least 2 image URLs.",
            }

        if len(image_urls) > 10:
            return {
                "success": False,
                "status": "validation_error",
                "error": "Meta limits Instagram carousels to a maximum of 10 items.",
            }

        for url in image_urls:
            is_local = (
                not str(url).lower().startswith("https://")
                or "127.0.0.1" in str(url).lower()
                or "localhost" in str(url).lower()
                or ".local/" in str(url).lower()
            )
            if is_local:
                return {
                    "success": False,
                    "status": "media_hosting_required",
                    "error": (
                        "Meta Graph API requires all carousel items to be hosted at publicly accessible HTTPS URLs. "
                        f"Local item detected: {url}"
                    ),
                    "export_ready": True,
                    "caption": caption,
                }

        cls._reload_env_if_needed(force=True)
        status = cls.get_status(force_refresh=True)
        if not status.get("can_publish"):
            return {
                "success": False,
                "status": status.get("status", "not_configured"),
                "error": status.get("message", "Instagram account not connected or missing permissions."),
                "caption": caption,
            }

        ig_user_id = str(status.get("account_id") or os.getenv("INSTAGRAM_ACCOUNT_ID", "")).strip()
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        api_version = cls.get_api_version()
        graph_base_url = cls.get_graph_base_url()
        auth_headers = {"Authorization": f"Bearer {access_token}"}
        if not ig_user_id:
            return {"success": False, "status": "not_configured", "error": "Instagram account ID is unavailable from the verified profile."}

        try:
            # Step 1: Create child item containers
            child_ids = []
            for img_url in image_urls:
                child_endpoint = f"{graph_base_url}/{api_version}/{ig_user_id}/media"
                child_payload = {
                    "image_url": img_url,
                    "is_carousel_item": "true",
                }
                child_res = requests.post(child_endpoint, data=child_payload, headers=auth_headers, timeout=(3, 20))
                if child_res.status_code != 200:
                    try:
                        err_json = child_res.json().get("error", {})
                    except Exception:
                        err_json = {}
                    err = err_json.get("message", child_res.text)
                    subcode = err_json.get("error_subcode")
                    if subcode == 33 or "Unsupported post request" in str(err) or "does not support this operation" in str(err):
                        err = (
                            f"Meta rejected target account ID '{ig_user_id}'. "
                            "Meta Graph API requires an Instagram Professional/Business Account ID (a numeric ID starting with 1784...), "
                            "not a Facebook User ID. In Meta Business Suite, assign your Instagram account to the System User under 'Assets' and put the Instagram Account ID in INSTAGRAM_ACCOUNT_ID."
                        )
                    return {"success": False, "status": "failed", "error": f"Child container creation failed: {err}"}
                cid = child_res.json().get("id")
                if not cid:
                    return {"success": False, "status": "failed", "error": "No child container ID returned by Meta API."}
                child_ids.append(cid)

            # Step 2: Create parent carousel container
            parent_endpoint = f"{graph_base_url}/{api_version}/{ig_user_id}/media"
            parent_payload = {
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption[:2200],
            }
            parent_res = requests.post(parent_endpoint, data=parent_payload, headers=auth_headers, timeout=(3, 20))
            if parent_res.status_code != 200:
                err = parent_res.json().get("error", {}).get("message", parent_res.text)
                return {"success": False, "status": "failed", "error": f"Carousel parent container creation failed: {err}"}

            carousel_container_id = parent_res.json().get("id")
            if not carousel_container_id:
                return {"success": False, "status": "failed", "error": "No carousel container ID returned by Meta API."}

            # Step 3: Publish container
            publish_url = f"{graph_base_url}/{api_version}/{ig_user_id}/media_publish"
            pub_res = requests.post(
                publish_url,
                data={"creation_id": carousel_container_id},
                headers=auth_headers,
                timeout=(3, 20),
            )
            if pub_res.status_code == 200:
                media_id = pub_res.json().get("id")
                global _ig_status_cache_time, _ig_status_cache_key
                _ig_status_cache_time = 0.0
                _ig_status_cache_key = ""
                return {
                    "success": True,
                    "status": "published",
                    "media_id": media_id,
                    "container_id": carousel_container_id,
                    "published": True,
                }
            else:
                err = pub_res.json().get("error", {}).get("message", pub_res.text)
                return {"success": False, "status": "failed", "error": f"Meta carousel publishing failed: {err}"}

        except Exception as exc:
            logger.exception("InstagramService.publish_carousel failed")
            return {"success": False, "status": "failed", "error": str(exc)}

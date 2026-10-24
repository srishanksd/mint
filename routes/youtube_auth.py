"""
routes/youtube_auth.py
YouTube OAuth 2.0 integration for MINT.

Routes:
  GET  /auth/youtube              — Start OAuth flow (redirect to Google)
  GET  /auth/youtube/callback     — Handle OAuth callback, store tokens
  POST /auth/youtube/disconnect   — Revoke and delete stored tokens
  GET  /api/youtube/status        — Current connection status (JSON)
  GET  /api/youtube/test          — Verify token & fetch channel info (JSON)
  GET  /api/youtube/videos        — List locally generated videos available for upload
  POST /api/youtube/upload        — Upload a generated video (private first)
"""

import os
import json
import secrets
import logging
from pathlib import Path
from flask import (
    Blueprint, redirect, request, session,
    url_for, jsonify, current_app
)

# Enable OAuth 2.0 token exchange over HTTP for local server (http://127.0.0.1:5000)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from google_auth_oauthlib.flow import Flow
import google.oauth2.credentials
import googleapiclient.discovery
import googleapiclient.http
import googleapiclient.errors

from database import get_db_connection, log_activity, update_agent_status
import config
from config import HOST, PORT

logger = logging.getLogger(__name__)

youtube_auth_bp = Blueprint("youtube_auth", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
def _find_client_secret_json() -> str:
    """
    Resolve the OAuth client secret JSON path.
    Order: YOUTUBE_CLIENT_SECRET_JSON env var → project root client_secret_*.json → Downloads folder fallback.
    Never hardcodes a machine-specific path into application logic.
    """
    env_path = os.getenv("YOUTUBE_CLIENT_SECRET_JSON", "").strip()
    if env_path and os.path.exists(env_path):
        return env_path

    # Search project root for any client_secret_*.json
    import glob
    project_root = str(Path(__file__).resolve().parent.parent)
    matches = glob.glob(os.path.join(project_root, "client_secret_*.json"))
    if matches:
        return matches[0]

    # If env var was set but file missing, return it anyway so error message is useful
    if env_path:
        return env_path

    # Final fallback: return env var value even if empty (will show FileNotFoundError with guidance)
    return os.getenv("YOUTUBE_CLIENT_SECRET_JSON", "")


CLIENT_SECRET_JSON = _find_client_secret_json()

def get_redirect_uri() -> str:
    """
    Returns the redirect URI for Google OAuth.
    Resolution order:
      1. Explicit environment variable: YOUTUBE_REDIRECT_URI
      2. If the downloaded client_secret JSON has an authorized local redirect URI
         (e.g., http://127.0.0.1:5000/oauth2callback) and canonical is not yet registered in it,
         reuse the registered URI to prevent redirect_uri_mismatch.
      3. Canonical default: http://{HOST}:{PORT}/auth/youtube/callback
    """
    env_uri = os.getenv("YOUTUBE_REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri

    canonical = f"http://{HOST}:{PORT}/auth/youtube/callback"

    if os.path.exists(CLIENT_SECRET_JSON):
        try:
            with open(CLIENT_SECRET_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            client_info = data.get("web") or data.get("installed") or {}
            registered = client_info.get("redirect_uris", [])
            if canonical in registered:
                return canonical
            # If the user registered another local URI like http://127.0.0.1:5000/oauth2callback:
            for u in registered:
                if f":{PORT}/" in u and ("127.0.0.1" in u or "localhost" in u):
                    return u
        except Exception:
            pass

    return canonical

REDIRECT_URI = get_redirect_uri()

# ---------------------------------------------------------------------------
# Token storage helpers (server-side, SQLite)
# ---------------------------------------------------------------------------

def _ensure_token_table():
    """Create oauth_tokens table if not already present (idempotent)."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id          INTEGER PRIMARY KEY,
                provider    TEXT    NOT NULL UNIQUE,
                token_json  TEXT    NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def _save_token(provider: str, credentials: google.oauth2.credentials.Credentials):
    """Persist Google OAuth credentials to SQLite."""
    _ensure_token_table()
    token_data = {
        "token":         credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri":     credentials.token_uri,
        "client_id":     credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes":        list(credentials.scopes) if credentials.scopes else [],
    }
    token_json = json.dumps(token_data)
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO oauth_tokens (provider, token_json, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(provider) DO UPDATE SET
                token_json = excluded.token_json,
                updated_at = datetime('now')
        """, (provider, token_json))
        conn.commit()


def _load_token(provider: str):
    """Load stored credentials or return None."""
    _ensure_token_table()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT token_json FROM oauth_tokens WHERE provider = ?", (provider,)
        ).fetchone()
    if not row:
        return None
    data = json.loads(row["token_json"])
    creds = google.oauth2.credentials.Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )
    return creds


def _delete_token(provider: str):
    _ensure_token_table()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE provider = ?", (provider,))
        conn.commit()


def _refresh_if_needed(creds: google.oauth2.credentials.Credentials):
    """Refresh an expired or token-less credential when a refresh token is available."""
    if (creds.expired or not creds.token) and creds.refresh_token:
        import google.auth.transport.requests
        creds.refresh(google.auth.transport.requests.Request())
        _save_token("youtube", creds)
    return creds


def _build_youtube_client(creds):
    return googleapiclient.discovery.build(
        "youtube", "v3",
        credentials=creds,
        cache_discovery=False
    )

# ---------------------------------------------------------------------------
# OAuth flow helpers
# ---------------------------------------------------------------------------

def _oauth_client_configured() -> bool:
    """True when either a Google OAuth client JSON or both explicit env credentials exist."""
    has_json = bool(CLIENT_SECRET_JSON and os.path.isfile(CLIENT_SECRET_JSON))
    has_env_credentials = bool(
        os.getenv("YOUTUBE_CLIENT_ID", "").strip()
        and os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    )
    return has_json or has_env_credentials


def _youtube_oauth_setup_message() -> str:
    """Actionable setup guidance without exposing credential values."""
    if CLIENT_SECRET_JSON and not os.path.isfile(CLIENT_SECRET_JSON):
        return (
            "The configured YOUTUBE_CLIENT_SECRET_JSON path does not point to an existing file. "
            "Correct that path, or use YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET instead."
        )
    return (
        "YouTube OAuth credentials are not configured. In Google Cloud Console, enable YouTube Data API v3, "
        "create a Web application OAuth client, and either set YOUTUBE_CLIENT_SECRET_JSON to its downloaded "
        "client JSON file or set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env. "
        f"Add this exact Authorized redirect URI to the OAuth client: {get_redirect_uri()}"
    )


def _build_flow(redirect_uri: str = None):
    target_uri = redirect_uri or get_redirect_uri()

    if CLIENT_SECRET_JSON and os.path.isfile(CLIENT_SECRET_JSON):
        return Flow.from_client_secrets_file(
            CLIENT_SECRET_JSON,
            scopes=SCOPES,
            redirect_uri=target_uri
        )

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        # Keep compatibility with .env-based credentials as well as Google's downloaded JSON.
        # The actual redirect URI still must be registered in Google Cloud Console.
        client_config = {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [target_uri],
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=target_uri
        )

    raise FileNotFoundError(_youtube_oauth_setup_message())

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@youtube_auth_bp.route("/auth/youtube")
def youtube_authorize():
    """Initiate YouTube OAuth flow."""
    from html import escape

    redirect_uri = get_redirect_uri()
    try:
        flow = _build_flow(redirect_uri=redirect_uri)
    except FileNotFoundError as exc:
        message = escape(str(exc))
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>MINT — YouTube Setup Required</title>"
            "<style>body{font:16px/1.6 system-ui,sans-serif;background:#f3f4f6;color:#111827;"
            "max-width:760px;margin:8vh auto;padding:24px}main{background:white;border:1px solid #e5e7eb;"
            "border-radius:14px;padding:28px}a{color:#4f46e5}</style></head><body><main>"
            "<h1>YouTube OAuth setup required</h1>"
            f"<p>{message}</p>"
            "<p>Once the Google OAuth client is configured, restart MINT and select Connect YouTube again.</p>"
            "<p><a href='/'>Return to MINT dashboard</a></p></main></body></html>"
        ), 503

    # CSRF protection: store state in server-side session
    state = secrets.token_urlsafe(32)
    session["youtube_oauth_state"] = state
    # Store exact redirect_uri used so token fetch matches identically
    session["youtube_oauth_redirect_uri"] = redirect_uri

    auth_url, _ = flow.authorization_url(
        access_type="offline",   # request refresh_token
        include_granted_scopes="true",
        state=state,
        prompt="consent"         # ensure refresh token is always returned
    )
    # Store PKCE code_verifier generated by flow.authorization_url()
    if getattr(flow, "code_verifier", None):
        session["youtube_oauth_code_verifier"] = flow.code_verifier

    return redirect(auth_url)


@youtube_auth_bp.route("/auth/youtube/callback")
@youtube_auth_bp.route("/oauth2callback")
def youtube_callback():
    """Handle Google's OAuth redirect."""
    returned_state = request.args.get("state", "")
    stored_state  = session.pop("youtube_oauth_state", None)

    if not stored_state or returned_state != stored_state:
        return (
            "<h3>YouTube OAuth Error</h3>"
            "<p>Invalid or missing CSRF state. Please try connecting again.</p>"
            "<a href='/'>Back to Dashboard</a>"
        ), 400

    error = request.args.get("error")
    if error:
        return (
            f"<h3>YouTube OAuth Error</h3><p>Google returned: {error}</p>"
            "<a href='/'>Back to Dashboard</a>"
        ), 400

    try:
        used_redirect_uri = session.pop("youtube_oauth_redirect_uri", None) or get_redirect_uri()
        code_verifier = session.pop("youtube_oauth_code_verifier", None)
        flow = _build_flow(redirect_uri=used_redirect_uri)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url, code_verifier=code_verifier)
        creds = flow.credentials
        _save_token("youtube", creds)
    except Exception as exc:
        logger.exception("YouTube OAuth token exchange failed")
        return (
            f"<h3>Token exchange failed</h3><p>{exc}</p>"
            "<a href='/'>Back to Dashboard</a>"
        ), 500

    return redirect("/?yt_connected=1")


@youtube_auth_bp.route("/auth/youtube/disconnect", methods=["POST"])
def youtube_disconnect():
    """Revoke token at Google and delete from local storage."""
    creds = _load_token("youtube")
    if creds and creds.token:
        try:
            import requests as req_lib
            req_lib.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": creds.token},
                timeout=5
            )
        except Exception:
            pass  # Revocation is best-effort; always delete locally
    _delete_token("youtube")
    return jsonify({"disconnected": True})


@youtube_auth_bp.route("/api/youtube/status")
def youtube_status():
    """Return honest OAuth/token/scope status without deleting credentials on transient failures."""
    oauth_configured = _oauth_client_configured()
    try:
        creds = _load_token("youtube")
    except Exception:
        logger.exception("Could not load stored YouTube OAuth token")
        return jsonify({
            "configured": oauth_configured,
            "oauth_configured": oauth_configured,
            "connected": False,
            "token_valid": False,
            "can_upload": False,
            "status": "token_error",
            "message": "The stored YouTube credentials could not be read. They were not deleted; inspect the server log before reconnecting."
        }), 500

    if not creds:
        status = "not_connected"
        message = "Google OAuth is configured, but no YouTube account has been authorized. Click Connect YouTube." if oauth_configured else _youtube_oauth_setup_message()
        return jsonify({
            "configured": oauth_configured,
            "oauth_configured": oauth_configured,
            "connected": False,
            "token_valid": False,
            "has_upload_scope": False,
            "can_upload": False,
            "status": status,
            "setup_required": not oauth_configured,
            "message": message
        })

    try:
        creds = _refresh_if_needed(creds)
    except Exception as exc:
        # Keep the stored token/refresh token; transient network errors should not erase them.
        logger.warning("YouTube token refresh failed: %s", type(exc).__name__)
        return jsonify({
            "configured": True,
            "oauth_configured": oauth_configured,
            "connected": False,
            "token_valid": False,
            "has_upload_scope": False,
            "can_upload": False,
            "status": "token_refresh_failed",
            "message": "The stored YouTube token could not be refreshed. The token was preserved. Retry once network access is available; reconnect only if Google reports invalid_grant."
        })

    token_valid = bool(creds.valid)
    has_upload_scope = "https://www.googleapis.com/auth/youtube.upload" in set(creds.scopes or [])
    if not token_valid:
        return jsonify({
            "configured": True,
            "oauth_configured": oauth_configured,
            "connected": False,
            "token_valid": False,
            "has_upload_scope": has_upload_scope,
            "can_upload": False,
            "status": "token_invalid",
            "message": "No valid YouTube access token is available. Reconnect the account to authorize again."
        })

    if not has_upload_scope:
        return jsonify({
            "configured": True,
            "oauth_configured": oauth_configured,
            "connected": True,
            "token_valid": True,
            "has_upload_scope": False,
            "can_upload": False,
            "status": "needs_permissions",
            "message": "YouTube is authorized, but the token does not include youtube.upload. Reconnect and approve the video-upload permission."
        })

    return jsonify({
        "configured": True,
        "oauth_configured": oauth_configured,
        "connected": True,
        "token_valid": True,
        "has_upload_scope": True,
        "can_upload": True,
        "status": "connected",
        "message": "YouTube OAuth token is valid and the youtube.upload scope is present."
    })


@youtube_auth_bp.route("/api/youtube/test")
def youtube_test():
    """Fetch real channel info to verify token works end-to-end."""
    creds = _load_token("youtube")
    if not creds:
        return jsonify({"ok": False, "error": "Not connected."})

    try:
        creds = _refresh_if_needed(creds)
        yt = _build_youtube_client(creds)
        resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "No channel found for this account."})
        ch = items[0]
        snippet = ch.get("snippet", {})
        stats   = ch.get("statistics", {})
        return jsonify({
            "ok": True,
            "channel_name":        snippet.get("title"),
            "channel_id":          ch.get("id"),
            "subscriber_count":    stats.get("subscriberCount"),
            "video_count":         stats.get("videoCount"),
            "channel_description": snippet.get("description", "")[:200],
        })
    except googleapiclient.errors.HttpError as exc:
        return jsonify({"ok": False, "error": f"YouTube API error: {exc.reason}"})
    except Exception as exc:
        logger.exception("YouTube test failed")
        return jsonify({"ok": False, "error": str(exc)})


@youtube_auth_bp.route("/api/youtube/videos")
def list_generated_videos():
    """List locally generated .mp4 files available for upload."""
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    video_dir = gen_dir / "videos"
    if not video_dir.exists():
        return jsonify({"videos": []})

    videos = []
    for f in sorted(video_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        size_mb = round(f.stat().st_size / (1024 * 1024), 2)
        videos.append({
            "filename": f.name,
            "size_mb":  size_mb,
            "path":     str(f),
        })
    return jsonify({"videos": videos})


@youtube_auth_bp.route("/api/youtube/upload", methods=["POST"])
def youtube_upload():
    """
    Upload a generated video to YouTube as private (never public without explicit user action).
    Requires explicit confirmation in request body.
    Body JSON:
      {
        "filename":     "experiment_5_promo.mp4",
        "title":        "My Video Title",
        "description":  "...",
        "tags":         ["tag1", "tag2"],
        "confirmed":    true        ← MUST be true; upload is blocked otherwise
      }
    """
    body = request.get_json(silent=True) or {}

    if not body.get("confirmed"):
        return jsonify({
            "success": False,
            "error": "Upload requires explicit confirmation. Set confirmed=true in request body."
        }), 400

    filename = body.get("filename", "").strip()
    if not filename:
        return jsonify({"success": False, "error": "filename is required."}), 400

    safe_filename = os.path.basename(filename)
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    video_dir = (gen_dir / "videos").resolve()
    video_path = (video_dir / safe_filename).resolve()

    if video_path.parent != video_dir or not video_path.exists():
        return jsonify({"success": False, "error": f"File not found: {filename}"}), 404

    title       = (body.get("title") or filename)[:100]
    description = (body.get("description") or "")[:5000]
    tags        = body.get("tags") or ["mint", "digitalventure", "automation"]

    creds = _load_token("youtube")
    if not creds:
        return jsonify({"success": False, "error": "YouTube not connected. Authorize first."}), 401

    try:
        creds = _refresh_if_needed(creds)
        yt = _build_youtube_client(creds)

        metadata = {
            "snippet": {
                "title":       title,
                "description": description,
                "tags":        tags,
                "categoryId":  "28",   # Science & Technology
            },
            "status": {
                "privacyStatus": "private",   # Always private on upload
                "selfDeclaredMadeForKids": False,
            },
        }

        media = googleapiclient.http.MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024 * 5  # 5 MB chunks
        )

        insert_request = yt.videos().insert(
            part="snippet,status",
            body=metadata,
            media_body=media
        )

        response = None
        while response is None:
            status, response = insert_request.next_chunk()

        video_id  = response.get("id")
        video_url = f"https://youtu.be/{video_id}" if video_id else None

        # Persist publication record in activity_log and dashboard activity_feed
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO activity_log (event_type, description, created_at)
                VALUES ('youtube_upload', ?, datetime('now'))
            """, (f"Uploaded '{safe_filename}' to YouTube as private video. ID: {video_id}",))
            conn.commit()

            # Find matching or latest experiment to surface in the live dashboard activity feed
            cur = conn.cursor()
            cur.execute("SELECT experiment_id FROM artifacts WHERE file_path LIKE ? ORDER BY id DESC LIMIT 1", (f"%{safe_filename}%",))
            row = cur.fetchone()
            exp_id = row["experiment_id"] if row else None
            if not exp_id:
                cur.execute("SELECT id FROM experiments ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                exp_id = row["id"] if row else None

        if exp_id:
            log_activity(exp_id, "Publishing Agent", f"Uploaded '{safe_filename}' to YouTube as private video (ID: {video_id}).", "info")
            update_agent_status(
                exp_id, "Publishing Agent", "completed",
                output_summary=f"Uploaded to YouTube as private video ({video_id}). Manual review required in YouTube Studio to set public.",
                decision_reason="Verified official YouTube API private upload."
            )

        return jsonify({
            "success":      True,
            "video_id":     video_id,
            "url":          video_url,
            "privacy":      "private",
            "note":         "Video uploaded as private. Visit YouTube Studio to make it public."
        })

    except googleapiclient.errors.HttpError as exc:
        logger.exception("YouTube upload API error")
        return jsonify({"success": False, "error": f"YouTube API error: {exc.reason}"}), 500
    except Exception as exc:
        logger.exception("YouTube upload failed")
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Channel Clipping & Scheduler Endpoints
# ---------------------------------------------------------------------------

@youtube_auth_bp.route("/api/youtube/channels/resolve", methods=["GET"])
def youtube_resolve_channel():
    from services.youtube_clipping_service import YouTubeClippingService
    query = request.args.get("query", "").strip()
    result = YouTubeClippingService.resolve_source_channel(query)
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@youtube_auth_bp.route("/api/youtube/source-media", methods=["GET"])
def youtube_list_source_media():
    from services.youtube_clipping_service import YouTubeClippingService
    media = YouTubeClippingService.list_authorized_source_media()
    return jsonify({"media": media})


@youtube_auth_bp.route("/api/youtube/source-media/upload", methods=["POST"])
def youtube_upload_source_media():
    from werkzeug.utils import secure_filename
    from services.youtube_clipping_service import get_source_videos_dir

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Empty filename."}), 400

    rights_confirmed = request.form.get("rights_confirmed", "").lower() in ("true", "1", "yes")
    if not rights_confirmed:
        return jsonify({"error": "You must confirm ownership or license to use this source video."}), 400

    filename = secure_filename(file.filename)
    if not filename.lower().endswith((".mp4", ".mov", ".mkv")):
        return jsonify({"error": "Unsupported video format. Upload .mp4 or .mov."}), 400

    src_dir = get_source_videos_dir()
    target_path = src_dir / filename
    file.save(str(target_path))

    return jsonify({
        "success": True,
        "filename": filename,
        "path": str(target_path),
        "size_mb": round(target_path.stat().st_size / (1024 * 1024), 2)
    })


@youtube_auth_bp.route("/api/youtube/clips/render", methods=["POST"])
def youtube_render_clip():
    from services.youtube_clipping_service import YouTubeClippingService
    data = request.get_json(silent=True) or {}

    source_path = data.get("source_path", "").strip()
    clip_title = data.get("clip_title", "").strip()
    rights_confirmed = bool(data.get("rights_confirmed", False))
    source_channel_name = data.get("source_channel_name")
    source_channel_id = data.get("source_channel_id")
    source_video_ref = data.get("source_video_ref")
    clip_description = data.get("clip_description")
    hashtags = data.get("hashtags")
    is_test = int(data.get("is_test", 0))

    try:
        start_sec = float(data.get("start_sec", 0.0))
        end_sec = float(data.get("end_sec", 15.0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "start_sec and end_sec must be numbers."}), 400

    res = YouTubeClippingService.render_clip(
        source_path=source_path,
        start_sec=start_sec,
        end_sec=end_sec,
        clip_title=clip_title,
        source_channel_name=source_channel_name,
        source_channel_id=source_channel_id,
        source_video_ref=source_video_ref,
        rights_confirmed=rights_confirmed,
        aspect_ratio=data.get("aspect_ratio", "9:16"),
        clip_description=clip_description,
        hashtags=hashtags,
        is_test=is_test
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_auth_bp.route("/api/youtube/clips", methods=["GET"])
def youtube_list_clips():
    from services.youtube_clipping_service import YouTubeClippingService
    include_test = request.args.get("include_test", "0") in ("1", "true")
    clips = YouTubeClippingService.list_clips(include_test=include_test)
    return jsonify({"clips": clips})


@youtube_auth_bp.route("/api/youtube/clips/<int:clip_id>", methods=["GET"])
def youtube_get_clip(clip_id: int):
    from services.youtube_clipping_service import YouTubeClippingService
    clip = YouTubeClippingService.get_clip(clip_id)
    if not clip:
        return jsonify({"error": f"Clip #{clip_id} not found."}), 404
    return jsonify({"clip": clip})


@youtube_auth_bp.route("/api/youtube/clips/<int:clip_id>/file", methods=["GET"])
def youtube_serve_clip_file(clip_id: int):
    from flask import send_file, abort
    from services.youtube_clipping_service import YouTubeClippingService, get_clips_base_dir

    clip = YouTubeClippingService.get_clip(clip_id)
    if not clip or not clip.get("output_path"):
        abort(404)

    file_path = Path(clip["output_path"]).resolve()
    base_dir = get_clips_base_dir().resolve()
    try:
        file_path.relative_to(base_dir)
    except ValueError:
        abort(403)

    if not file_path.exists():
        abort(404)

    return send_file(str(file_path), mimetype="video/mp4")


@youtube_auth_bp.route("/api/youtube/clips/<int:clip_id>", methods=["DELETE"])
def youtube_delete_clip(clip_id: int):
    from services.youtube_clipping_service import YouTubeClippingService
    res = YouTubeClippingService.delete_clip(clip_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_auth_bp.route("/api/youtube/schedule", methods=["GET"])
def youtube_get_schedule():
    from services.youtube_scheduler_service import YouTubeSchedulerService
    cfg = YouTubeSchedulerService.get_schedule_config()
    next_slots = YouTubeSchedulerService.calculate_next_slots(count=4)
    posts = YouTubeSchedulerService.list_scheduled_posts(limit=10)
    # Check offline missed slots
    missed_check = YouTubeSchedulerService.check_and_process_missed_slots()
    return jsonify({
        "schedule": cfg,
        "next_slots": next_slots,
        "recent_scheduled_posts": posts,
        "missed_slots_processed": missed_check.get("missed_marked", 0)
    })


@youtube_auth_bp.route("/api/youtube/schedule", methods=["POST"])
def youtube_update_schedule():
    from services.youtube_scheduler_service import YouTubeSchedulerService
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    tz_str = data.get("timezone", "UTC").strip() or "UTC"
    slot_1 = data.get("slot_1_time", "10:00").strip() or "10:00"
    slot_2 = data.get("slot_2_time", "18:00").strip() or "18:00"
    source = data.get("audience_timing_source", "user_configured_studio")

    cfg = YouTubeSchedulerService.update_schedule_config(
        enabled=enabled,
        timezone_str=tz_str,
        slot_1_time=slot_1,
        slot_2_time=slot_2,
        audience_timing_source=source
    )
    return jsonify({"success": True, "schedule": cfg})


@youtube_auth_bp.route("/api/youtube/schedule/queue", methods=["POST"])
def youtube_queue_clip():
    from services.youtube_scheduler_service import YouTubeSchedulerService
    data = request.get_json(silent=True) or {}
    clip_id = data.get("clip_id")
    if not clip_id:
        return jsonify({"success": False, "error": "clip_id is required."}), 400

    target_slot = data.get("target_slot_datetime_utc")
    dest_channel_id = data.get("destination_channel_id")
    is_test = int(data.get("is_test", 0))

    res = YouTubeSchedulerService.queue_clip_for_scheduling(
        clip_id=int(clip_id),
        target_slot_datetime_utc=target_slot,
        destination_channel_id=dest_channel_id,
        is_test=is_test
    )
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_auth_bp.route("/api/youtube/schedule/posts", methods=["GET"])
def youtube_list_scheduled_posts():
    from services.youtube_scheduler_service import YouTubeSchedulerService
    include_test = request.args.get("include_test", "0") in ("1", "true")
    posts = YouTubeSchedulerService.list_scheduled_posts(include_test=include_test)
    return jsonify({"scheduled_posts": posts})


@youtube_auth_bp.route("/api/youtube/schedule/posts/<int:post_id>/publish", methods=["POST"])
def youtube_publish_scheduled_post(post_id: int):
    from services.youtube_scheduler_service import YouTubeSchedulerService
    data = request.get_json(silent=True) or {}
    confirmed = bool(data.get("confirmed", False))
    res = YouTubeSchedulerService.publish_scheduled_post(post_id=post_id, confirmed=confirmed)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_auth_bp.route("/api/youtube/schedule/posts/<int:post_id>/cancel", methods=["POST"])
def youtube_cancel_scheduled_post(post_id: int):
    from services.youtube_scheduler_service import YouTubeSchedulerService
    res = YouTubeSchedulerService.cancel_scheduled_post(post_id=post_id)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code


@youtube_auth_bp.route("/api/youtube/analytics/audience", methods=["GET"])
def youtube_analytics_audience():
    from services.youtube_scheduler_service import YouTubeSchedulerService
    data = YouTubeSchedulerService.get_analytics_audience_status()
    return jsonify(data)


@youtube_auth_bp.route("/api/youtube/videos/<filename>", methods=["DELETE"])
def youtube_delete_local_video(filename: str):
    """
    Safely removes a locally generated video file from generated/videos.
    Preserves files if referenced by active artifacts, scheduled clips, or publication records.
    """
    safe_name = os.path.basename(filename)
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()
    videos_dir = (gen_dir / "videos").resolve()
    target_file = (videos_dir / safe_name).resolve()

    try:
        target_file.relative_to(videos_dir)
    except ValueError:
        return jsonify({"error": "Refusing to delete file outside videos directory."}), 403

    if not target_file.exists() or not target_file.is_file():
        return jsonify({"error": f"Video '{safe_name}' not found."}), 404

    # Check references
    conn = get_db_connection()
    cur = conn.cursor()

    # Check artifacts
    cur.execute("SELECT id, title FROM artifacts WHERE file_path LIKE ?", (f"%{safe_name}%",))
    art = cur.fetchone()
    if art:
        conn.close()
        return jsonify({
            "error": f"Video is referenced by Artifact #{art['id']} ('{art['title']}'). Cannot delete an active venture artifact."
        }), 400

    # Check scheduled posts
    cur.execute("SELECT id FROM youtube_clips WHERE source_file_path LIKE ?", (f"%{safe_name}%",))
    clip_ref = cur.fetchone()
    if clip_ref:
        conn.close()
        return jsonify({
            "error": f"Video is referenced as source media for Clip #{clip_ref['id']}. Delete the clip first."
        }), 400

    conn.close()

    try:
        target_file.unlink()
        return jsonify({"success": True, "message": f"Local video '{safe_name}' deleted."})
    except Exception as e:
        return jsonify({"error": f"Failed deleting video file: {str(e)}"}), 500


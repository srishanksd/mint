"""
services/lumiclip_service.py
Official LumiClip REST API Client for MINT.

Official References:
- API Documentation: https://www.lumiclip.ai/api
- Base URL: https://api.lumiclip.ai
- Authentication: Bearer <LUMICLIP_API_KEY>

Endpoints:
- POST /api/v1/clips/generate   (Submit YouTube video URL for clipping)
- GET  /api/v1/projects/{id}    (Poll clipping job status and clips)
- GET  /api/v1/projects         (List prior projects)
- GET  /api/v1/clips/{id}       (Retrieve clip details)
- POST /api/v1/clips/{id}/export (Export a clip at supported resolution: 720p default)
- GET  /api/v1/clips/{id}/download (Retrieve signed MP4 download URL)
- GET  /api/v1/account/usage    (Check plan and remaining credits)
"""

import os
import re
import time
import json
import logging
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

import config

logger = logging.getLogger(__name__)

LUMICLIP_BASE_URL = os.getenv("LUMICLIP_BASE_URL", "https://api.lumiclip.ai").rstrip("/")
_USAGE_CACHE: Optional[Dict[str, Any]] = None
_USAGE_CACHE_TIME: float = 0
_USAGE_CACHE_TTL: float = 60.0  # Cache usage lookups for 60 seconds


def get_youtube_clips_base_dir() -> Path:
    """Organized single root for YouTube clips: generated/content/youtube_clips/."""
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    clips_dir = gen_dir / "content" / "youtube_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    return clips_dir


class LumiClipService:
    """
    Dedicated client for the LumiClip AI video clipping engine.
    Enforces authentication safety: the API key is never logged or exposed in client payloads.
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
    def get_api_key(cls) -> str:
        cls._reload_env_if_needed()
        return os.getenv("LUMICLIP_API_KEY", "").strip()

    @classmethod
    def _get_headers(cls) -> Dict[str, str]:
        key = cls.get_api_key()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MINT-Autonomous-Creator/1.0"
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    @classmethod
    def _log_api_error(cls, endpoint: str, error: Any, res: Optional[requests.Response] = None):
        """Logs complete LumiClip API error details to terminal/console and logger."""
        err_header = f"\n{'='*70}\n[LUMICLIP API ERROR] Endpoint: {endpoint}\n{'='*70}"
        details = []
        if res is not None:
            details.append(f"HTTP Status Code : {res.status_code}")
            details.append(f"Response URL     : {getattr(res, 'url', 'N/A')}")
            details.append(f"Response Headers : {dict(getattr(res, 'headers', {}))}")
            try:
                details.append(f"Response Body    : {res.text}")
            except Exception:
                details.append(f"Response Body    : <unreadable>")
        if error:
            details.append(f"Exception/Details: {repr(error)}")
            if isinstance(error, Exception):
                details.append(f"Traceback:\n{traceback.format_exc()}")
        full_msg = f"{err_header}\n" + "\n".join(details) + f"\n{'='*70}\n"
        print(full_msg, flush=True)
        logger.error(full_msg)

    @classmethod
    def get_status(cls, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Queries GET /api/v1/account/usage to verify key validity and credit allowance.
        Does not falsely report connected without a live check.
        """
        global _USAGE_CACHE, _USAGE_CACHE_TIME

        cls._reload_env_if_needed(force=force_refresh)
        key = cls.get_api_key()

        if not key:
            return {
                "configured": False,
                "status": "not_configured",
                "can_clip": False,
                "plan": None,
                "credits_remaining": None,
                "credits_used": None,
                "credits_total": None,
                "active_jobs": 0,
                "message": "LumiClip API key is not configured. Add LUMICLIP_API_KEY to your .env file.",
                "setup_required": ["Add LUMICLIP_API_KEY=<your_key> to .env"]
            }

        now = time.time()
        if not force_refresh and _USAGE_CACHE and (now - _USAGE_CACHE_TIME) < _USAGE_CACHE_TTL:
            return dict(_USAGE_CACHE, cache_hit=True)

        url = f"{LUMICLIP_BASE_URL}/api/v1/account/usage"
        try:
            res = requests.get(url, headers=cls._get_headers(), timeout=(4, 12))
            if res.status_code == 200:
                data = res.json() if res.text else {}
                # Support nested structures like { "usage": {...} } or direct keys
                usage_info = data.get("usage", data)
                plan = usage_info.get("plan", data.get("plan", "Standard"))
                credits_remaining = usage_info.get("credits_remaining", data.get("credits_remaining"))
                credits_used = usage_info.get("credits_used", data.get("credits_used"))
                credits_total = usage_info.get("credits_total", data.get("credits_total"))

                # Determine status based on credits
                status = "connected"
                can_clip = True
                msg = f"Connected to LumiClip ({plan} plan)."

                if credits_remaining is not None:
                    try:
                        cr_num = float(credits_remaining)
                        if cr_num <= 0:
                            status = "credits_exhausted"
                            can_clip = False
                            msg = f"LumiClip credits exhausted (0 remaining on {plan} plan)."
                        elif cr_num < 15:
                            status = "credits_low"
                            msg = f"LumiClip credits low ({cr_num} remaining on {plan} plan)."
                        else:
                            msg = f"Connected to LumiClip ({plan} plan, {cr_num} credits remaining)."
                    except (ValueError, TypeError):
                        pass

                result = {
                    "configured": True,
                    "status": status,
                    "can_clip": can_clip,
                    "plan": plan,
                    "credits_remaining": credits_remaining,
                    "credits_used": credits_used,
                    "credits_total": credits_total,
                    "active_jobs": data.get("active_jobs", 0),
                    "message": msg,
                    "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                _USAGE_CACHE = result
                _USAGE_CACHE_TIME = now
                return dict(result, cache_hit=False)

            elif res.status_code == 401:
                cls._log_api_error(url, "Authentication 401", res=res)
                return {
                    "configured": True,
                    "status": "token_invalid",
                    "can_clip": False,
                    "plan": None,
                    "credits_remaining": None,
                    "message": "LumiClip API key was rejected (HTTP 401). Verify LUMICLIP_API_KEY in .env.",
                    "setup_required": ["Check LUMICLIP_API_KEY for validity at https://www.lumiclip.ai/"]
                }
            elif res.status_code == 429:
                cls._log_api_error(url, "Rate limited 429", res=res)
                return {
                    "configured": True,
                    "status": "rate_limited",
                    "can_clip": False,
                    "plan": None,
                    "credits_remaining": None,
                    "message": "LumiClip rate limit exceeded (HTTP 429). Please wait before retrying."
                }
            else:
                cls._log_api_error(url, f"Unexpected HTTP {res.status_code}", res=res)
                err_msg = res.json().get("error", {}).get("message", res.text) if res.text else f"HTTP {res.status_code}"
                return {
                    "configured": True,
                    "status": "request_failed",
                    "can_clip": False,
                    "plan": None,
                    "credits_remaining": None,
                    "message": f"LumiClip account check returned HTTP {res.status_code}: {err_msg[:200]}"
                }

        except requests.exceptions.Timeout as e:
            cls._log_api_error(url, e)
            return {
                "configured": True,
                "status": "service_temporarily_unavailable",
                "can_clip": False,
                "message": "LumiClip connection timed out. Service may be temporarily unavailable."
            }
        except requests.exceptions.ConnectionError as e:
            cls._log_api_error(url, e)
            return {
                "configured": True,
                "status": "service_temporarily_unavailable",
                "can_clip": False,
                "message": "Unable to connect to LumiClip API. Check your internet connection."
            }
        except Exception as e:
            cls._log_api_error(url, e)
            return {
                "configured": True,
                "status": "service_temporarily_unavailable",
                "can_clip": False,
                "message": f"LumiClip client error: {str(e)[:150]}"
            }

    @classmethod
    def submit_clipping_project(
        cls,
        video_url: str,
        title: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        callback_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits a YouTube video URL to POST /api/v1/clips/generate.
        Returns project ID asynchronously (HTTP 202/200).
        """
        if not video_url or not str(video_url).strip():
            return {"success": False, "status": "validation_error", "error": "A valid YouTube video URL is required."}

        clean_url = str(video_url).strip()
        # Verify it's a YouTube URL
        is_yt = bool(re.search(r"(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)[A-Za-z0-9_-]{6,}", clean_url))
        if not is_yt:
            return {
                "success": False,
                "status": "invalid_url",
                "error": "The supplied URL must be a valid YouTube video or Shorts link (e.g., https://youtube.com/watch?v=...)."
            }

        # Check account readiness first
        status = cls.get_status()
        if not status.get("can_clip"):
            return {
                "success": False,
                "status": status.get("status", "not_ready"),
                "error": status.get("message", "LumiClip engine is not ready to process videos.")
            }

        payload: Dict[str, Any] = {"url": clean_url}
        if title:
            payload["title"] = str(title).strip()
        if start_time is not None and start_time >= 0:
            payload["start_time"] = float(start_time)
        if end_time is not None and end_time > 0:
            payload["end_time"] = float(end_time)
        if callback_url and callback_url.startswith("https://"):
            payload["callback_url"] = callback_url

        url = f"{LUMICLIP_BASE_URL}/api/v1/clips/generate"
        try:
            res = requests.post(url, json=payload, headers=cls._get_headers(), timeout=(5, 20))
            if res.status_code in (200, 201, 202):
                data = res.json() if res.text else {}
                project_id = str(data.get("project_id") or data.get("id") or "").strip()
                if not project_id:
                    return {
                        "success": False,
                        "status": "provider_error",
                        "error": "LumiClip accepted the request but did not return a project ID."
                    }
                return {
                    "success": True,
                    "status": "processing",
                    "project_id": project_id,
                    "message": f"Successfully queued video for AI clipping. Project ID: {project_id}",
                    "data": data
                }
            elif res.status_code == 400:
                cls._log_api_error(url, "Bad Request 400", res=res)
                err = res.json().get("error", {}).get("message", res.text) if res.text else "Bad request"
                err_lower = str(err).lower()
                guidance = "The supplied video cannot be processed by LumiClip."
                if any(w in err_lower for w in ("authentication", "sign in", "sign-in", "login", "cookie", "restricted", "private", "age")):
                    guidance = "This video is restricted or requires YouTube sign-in. Please select an eligible public YouTube video."
                return {"success": False, "status": "bad_request", "error": f"LumiClip rejected video URL: {err}", "actionable_guidance": guidance}
            elif res.status_code == 401:
                cls._log_api_error(url, "Authentication 401", res=res)
                return {"success": False, "status": "unauthorized", "error_type": "invalid_api_key", "error": "LumiClip authentication failed (HTTP 401). Verify LUMICLIP_API_KEY in .env.", "actionable_guidance": "Check and configure LUMICLIP_API_KEY in .env."}
            elif res.status_code == 402 or "credit" in res.text.lower():
                cls._log_api_error(url, "Credits exhausted 402", res=res)
                return {"success": False, "status": "credits_exhausted", "error_type": "insufficient_credits", "error": "Insufficient LumiClip credits to process this video.", "actionable_guidance": "Upgrade or add credits on https://www.lumiclip.ai/ to generate clips."}
            else:
                cls._log_api_error(url, f"Unexpected HTTP {res.status_code}", res=res)
                err = res.json().get("error", {}).get("message", res.text) if res.text else f"HTTP {res.status_code}"
                return {"success": False, "status": "failed", "error_type": "provider_error", "error": f"LumiClip project creation failed: {err}", "actionable_guidance": "LumiClip server rejected request. Please check source URL."}
        except requests.exceptions.Timeout as e:
            cls._log_api_error(url, e)
            return {"success": False, "status": "timeout", "error_type": "network_timeout", "error": "LumiClip submission timed out. Please retry.", "actionable_guidance": "Network connection timed out. Check connectivity."}
        except Exception as e:
            cls._log_api_error(url, e)
            return {"success": False, "status": "network_error", "error_type": "network_error", "error": f"Network error submitting to LumiClip: {str(e)[:150]}", "actionable_guidance": "Network error reaching LumiClip. Check connection."}

    # Alias for convenience and provider consistency
    create_project = submit_clipping_project

    @classmethod
    def get_project(cls, project_id: str) -> Dict[str, Any]:
        """
        Polls GET /api/v1/projects/{id} to retrieve project state, step, clips and failures.
        Accurately parses provider response fields: status, step, error, and clips.
        """
        if not project_id:
            return {"success": False, "status": "validation_error", "error": "Project ID is required."}

        url = f"{LUMICLIP_BASE_URL}/api/v1/projects/{project_id}"
        try:
            res = requests.get(url, headers=cls._get_headers(), timeout=(5, 15))
            if res.status_code == 200:
                data = res.json() if res.text else {}
                proj_data = data.get("project", data)
                state = str(proj_data.get("status") or "processing").lower()
                step = str(proj_data.get("step") or "").upper()
                error = proj_data.get("error") or data.get("error")
                clips = proj_data.get("clips") or data.get("clips") or []

                raw_progress = proj_data.get("progress") if proj_data.get("progress") is not None else data.get("progress")
                if raw_progress is not None:
                    try:
                        progress = int(raw_progress)
                    except (ValueError, TypeError):
                        progress = 0
                else:
                    if state in ("completed", "done", "finished"):
                        progress = 100
                    elif state in ("failed", "error"):
                        progress = 0
                    else:
                        progress = 0

                title = proj_data.get("name") or proj_data.get("title") or proj_data.get("video_title")

                # Actionable guidance classification
                error_type = None
                actionable_guidance = None
                if state in ("failed", "error") or error:
                    err_str = str(error or "LumiClip video processing failed")
                    err_lower = err_str.lower()
                    if any(w in err_lower for w in ("authentication", "sign in", "sign-in", "login", "cookie", "restricted", "private", "age")):
                        error_type = "video_inaccessible"
                        actionable_guidance = "This video requires YouTube authentication or is restricted. Select a public, unrestricted YouTube video."
                    else:
                        error_type = "provider_failure"
                        actionable_guidance = f"LumiClip processing failed: {err_str}"

                return {
                    "success": True,
                    "project_id": project_id,
                    "status": state,
                    "step": step,
                    "error": error,
                    "error_type": error_type,
                    "actionable_guidance": actionable_guidance,
                    "progress": progress,
                    "clips": clips,
                    "clips_count": len(clips),
                    "video_title": title,
                    "raw": data
                }
            elif res.status_code == 401:
                cls._log_api_error(url, "Authentication 401", res=res)
                return {
                    "success": False,
                    "status": "unauthorized",
                    "error_type": "invalid_api_key",
                    "error": "LumiClip API authentication failed (HTTP 401). Verify LUMICLIP_API_KEY in .env.",
                    "actionable_guidance": "Check and update LUMICLIP_API_KEY in .env."
                }
            elif res.status_code == 402 or "credit" in res.text.lower():
                cls._log_api_error(url, "Credits exhausted 402", res=res)
                return {
                    "success": False,
                    "status": "credits_exhausted",
                    "error_type": "insufficient_credits",
                    "error": "Insufficient LumiClip credits.",
                    "actionable_guidance": "Upgrade or add credits on https://www.lumiclip.ai/ to generate clips."
                }
            elif res.status_code == 404:
                cls._log_api_error(url, "Not Found 404", res=res)
                return {
                    "success": False,
                    "status": "not_found",
                    "error_type": "not_found",
                    "error": f"Project {project_id} not found on LumiClip.",
                    "actionable_guidance": "The project ID does not exist on LumiClip. Verify project ID or start a new clipping job."
                }
            elif res.status_code == 429:
                cls._log_api_error(url, "Rate limited 429", res=res)
                return {
                    "success": False,
                    "status": "rate_limited",
                    "error_type": "rate_limited",
                    "error": "LumiClip rate limit exceeded (HTTP 429). Please wait before retrying.",
                    "actionable_guidance": "LumiClip rate limits active. Backing off request rate."
                }
            else:
                cls._log_api_error(url, f"Unexpected HTTP {res.status_code}", res=res)
                err = res.json().get("error", {}).get("message", res.text) if res.text else f"HTTP {res.status_code}"
                return {
                    "success": False,
                    "status": "failed",
                    "error_type": "provider_error",
                    "error": f"LumiClip project poll error: {err}",
                    "actionable_guidance": "LumiClip server encountered an error. Try again shortly."
                }
        except requests.exceptions.Timeout as e:
            cls._log_api_error(url, e)
            return {
                "success": False,
                "status": "timeout",
                "error_type": "network_timeout",
                "error": "LumiClip polling request timed out.",
                "actionable_guidance": "Network connection timed out while polling LumiClip."
            }
        except Exception as e:
            cls._log_api_error(url, e)
            return {
                "success": False,
                "status": "network_error",
                "error_type": "network_error",
                "error": f"Failed to reach LumiClip: {str(e)[:150]}",
                "actionable_guidance": "Network error reaching LumiClip. Check connection."
            }

    @classmethod
    def list_projects(cls, limit: int = 20) -> Dict[str, Any]:
        """
        Retrieves list of recent clipping projects: GET /api/v1/projects.
        """
        url = f"{LUMICLIP_BASE_URL}/api/v1/projects"
        try:
            res = requests.get(url, params={"limit": limit}, headers=cls._get_headers(), timeout=(4, 15))
            if res.status_code == 200:
                data = res.json() if res.text else {}
                projects = data.get("projects", data) if isinstance(data, dict) else data
                if not isinstance(projects, list):
                    projects = []
                return {"success": True, "projects": projects, "count": len(projects)}
            cls._log_api_error(url, f"List projects failed HTTP {res.status_code}", res=res)
            return {"success": False, "error": f"Failed listing projects (HTTP {res.status_code})", "projects": []}
        except Exception as e:
            cls._log_api_error(url, e)
            return {"success": False, "error": str(e), "projects": []}

    @classmethod
    def get_clip(cls, clip_id: str) -> Dict[str, Any]:
        """
        Retrieves clip details: GET /api/v1/clips/{id}.
        """
        if not clip_id:
            return {"success": False, "error": "Clip ID is required."}

        url = f"{LUMICLIP_BASE_URL}/api/v1/clips/{clip_id}"
        try:
            res = requests.get(url, headers=cls._get_headers(), timeout=(4, 12))
            if res.status_code == 200:
                data = res.json() if res.text else {}
                clip = data.get("clip", data)
                return {"success": True, "clip": clip}
            cls._log_api_error(url, f"Get clip failed HTTP {res.status_code}", res=res)
            return {"success": False, "error": f"Clip #{clip_id} not found (HTTP {res.status_code})"}
        except Exception as e:
            cls._log_api_error(url, e)
            return {"success": False, "error": str(e)}

    @classmethod
    def export_clip(cls, clip_id: str, quality: str = "720p") -> Dict[str, Any]:
        """
        Exports a clip as MP4: POST /api/v1/clips/{id}/export.
        Defaults to 720p to honor free-tier allowances.
        """
        if not clip_id:
            return {"success": False, "error": "Clip ID is required."}

        url = f"{LUMICLIP_BASE_URL}/api/v1/clips/{clip_id}/export"
        payload = {"quality": quality}
        try:
            res = requests.post(url, json=payload, headers=cls._get_headers(), timeout=(5, 25))
            if res.status_code in (200, 201, 202):
                data = res.json() if res.text else {}
                return {
                    "success": True,
                    "clip_id": clip_id,
                    "status": data.get("status", "exporting"),
                    "download_url": data.get("download_url") or data.get("url"),
                    "data": data
                }
            cls._log_api_error(url, f"Export clip failed HTTP {res.status_code}", res=res)
            err = res.json().get("error", {}).get("message", res.text) if res.text else f"HTTP {res.status_code}"
            return {"success": False, "status": "failed", "error": f"LumiClip export failed: {err}"}
        except Exception as e:
            cls._log_api_error(url, e)
            return {"success": False, "status": "error", "error": str(e)}

    @classmethod
    def get_download_url(cls, clip_id: str) -> Dict[str, Any]:
        """
        Retrieves a signed download URL: GET /api/v1/clips/{id}/download.
        """
        if not clip_id:
            return {"success": False, "error": "Clip ID is required."}

        url = f"{LUMICLIP_BASE_URL}/api/v1/clips/{clip_id}/download"
        try:
            res = requests.get(url, headers=cls._get_headers(), timeout=(4, 15))
            if res.status_code == 200:
                data = res.json() if res.text else {}
                dl_url = data.get("download_url") or data.get("url")
                if not dl_url:
                    return {"success": False, "error": "No download URL returned by LumiClip."}
                return {
                    "success": True,
                    "download_url": dl_url,
                    "expires_at": data.get("expires_at")
                }
            cls._log_api_error(url, f"Get download URL failed HTTP {res.status_code}", res=res)
            err = res.json().get("error", {}).get("message", res.text) if res.text else f"HTTP {res.status_code}"
            return {"success": False, "error": f"Download URL retrieval failed: {err}"}
        except Exception as e:
            cls._log_api_error(url, e)
            return {"success": False, "error": str(e)}

    @classmethod
    def download_and_verify_mp4(cls, download_url: str, dest_path: Path) -> Dict[str, Any]:
        """
        Downloads the MP4 stream to dest_path, enforcing:
        1. Safe write into single organized root
        2. Non-empty file (> 10KB)
        3. MP4 magic byte verification ('ftyp' in first 32 bytes)
        Never fabricates placeholder MP4s.
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with requests.get(download_url, stream=True, timeout=(6, 60)) as res:
                if res.status_code != 200:
                    cls._log_api_error(download_url, f"Download MP4 failed HTTP {res.status_code}", res=res)
                    return {
                        "success": False,
                        "error": f"Failed downloading clip MP4: HTTP {res.status_code}"
                    }

                bytes_written = 0
                max_bytes = 150 * 1024 * 1024  # 150 MB safety limit for shorts

                with open(dest_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            bytes_written += len(chunk)
                            if bytes_written > max_bytes:
                                dest_path.unlink(missing_ok=True)
                                return {"success": False, "error": "Downloaded clip exceeded 150MB safety limit."}

            if not dest_path.exists() or bytes_written < 10240:
                dest_path.unlink(missing_ok=True)
                return {"success": False, "error": "Downloaded file is corrupted or below minimum valid MP4 size (10KB)."}

            # Validate MP4 header (magic bytes: 'ftyp')
            has_ftyp = False
            with open(dest_path, "rb") as f:
                header = f.read(32)
                has_ftyp = (b"ftyp" in header)

            if not has_ftyp:
                dest_path.unlink(missing_ok=True)
                return {"success": False, "error": "Downloaded file header does not contain standard MP4 container identifier ('ftyp')."}

            return {
                "success": True,
                "file_path": str(dest_path.resolve()),
                "file_size_bytes": bytes_written
            }

        except Exception as e:
            dest_path.unlink(missing_ok=True)
            return {"success": False, "error": f"Error downloading MP4: {str(e)[:150]}"}

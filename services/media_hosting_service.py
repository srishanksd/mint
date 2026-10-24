"""
services/media_hosting_service.py
Public HTTPS Media Hosting Adapter for MINT.

Meta Graph API requires all Instagram publishing media to be hosted at a
publicly accessible HTTPS URL before Meta servers can fetch it.
Local files (e.g. D:\\chronoforge\\..., localhost, 127.0.0.1) cannot be fetched by Meta.

Supports:
1. Cloudinary (via signed REST API upload)
2. Custom Public Media Host (via PUBLIC_MEDIA_BASE_URL)
3. Clear unconfigured state with actionable next steps (no secrets leaked)
"""

import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import requests
from PIL import Image

import config

logger = logging.getLogger(__name__)


class MediaHostingService:
    """
    Manages external public HTTPS media hosting for Meta/Instagram publishing.
    """

    @classmethod
    def _reload_env_if_needed(cls):
        import sys
        if any(m in sys.modules for m in ["unittest", "pytest"]):
            return
        try:
            from dotenv import load_dotenv
            env_file = Path(__file__).resolve().parent.parent / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=False)
                if not os.getenv("CLOUDINARY_CLOUD_NAME"):
                    load_dotenv(env_file, override=True)
        except Exception:
            pass

    @classmethod
    def get_provider(cls) -> str:
        cls._reload_env_if_needed()
        if (
            os.getenv("CLOUDINARY_CLOUD_NAME")
            and os.getenv("CLOUDINARY_API_KEY")
            and os.getenv("CLOUDINARY_API_SECRET")
        ):
            return "cloudinary"
        if os.getenv("PUBLIC_MEDIA_BASE_URL", "").lower().startswith("https://"):
            return "custom_url"
        return "none"

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """
        Returns media hosting readiness without leaking credentials.
        """
        provider = cls.get_provider()
        if provider == "cloudinary":
            cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
            # Redact cloud name slightly for display
            masked_name = f"{cloud_name[:3]}***" if len(cloud_name) > 3 else "configured"
            return {
                "configured": True,
                "can_host": True,
                "provider": "cloudinary",
                "provider_label": f"Cloudinary ({masked_name})",
                "message": "Public HTTPS media hosting ready via Cloudinary.",
            }
        elif provider == "custom_url":
            base_url = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip()
            return {
                "configured": True,
                "can_host": True,
                "provider": "custom_url",
                "provider_label": "Custom HTTPS Media Host",
                "message": f"Public media hosting configured via {base_url[:30]}...",
            }
        else:
            return {
                "configured": False,
                "can_host": False,
                "provider": "none",
                "provider_label": "Not configured",
                "message": (
                    "Public HTTPS media hosting is not configured. Meta cannot fetch local files from your disk. "
                    "Configure Cloudinary (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) "
                    "or PUBLIC_MEDIA_BASE_URL in your .env file to enable live Instagram publishing."
                ),
                "setup_required": [
                    "Option A: Add CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET to .env",
                    "Option B: Expose generated media via HTTPS tunnel/CDN and set PUBLIC_MEDIA_BASE_URL in .env",
                    "Local generation, preview, and manual export remain fully functional without hosting."
                ]
            }

    @classmethod
    def upload_image(cls, local_path: str) -> Dict[str, Any]:
        """
        Uploads an image to the configured public media host.
        Returns {"success": True, "public_url": "https://..."} or an honest error dict.
        """
        status = cls.get_status()
        if not status.get("can_host"):
            return {
                "success": False,
                "status": "hosting_not_configured",
                "error": status["message"],
                "setup_required": status.get("setup_required", [])
            }

        file_obj = Path(local_path)
        if not file_obj.exists() or not file_obj.is_file():
            return {
                "success": False,
                "status": "file_not_found",
                "error": f"Local media file not found: {local_path}",
            }

        # Verify it is a valid image with Pillow
        try:
            with Image.open(str(file_obj)) as im:
                im.verify()
        except Exception as pe:
            return {
                "success": False,
                "status": "invalid_media",
                "error": f"File is not a valid readable image: {str(pe)}"
            }

        provider = status.get("provider")
        if provider == "cloudinary":
            return cls._upload_to_cloudinary(file_obj)
        elif provider == "custom_url":
            return cls._resolve_custom_url(file_obj)
        else:
            return {
                "success": False,
                "status": "unsupported_provider",
                "error": f"Unsupported media hosting provider: {provider}"
            }

    @classmethod
    def _upload_to_cloudinary(cls, file_obj: Path) -> Dict[str, Any]:
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
        api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
        api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()

        if not cloud_name or not api_key or not api_secret:
            return {"success": False, "status": "incomplete_credentials", "error": "Missing Cloudinary credentials."}

        timestamp = int(time.time())
        # Cloudinary signed upload signature: sha1("folder=mint_media&timestamp=<ts><api_secret>")
        folder = "mint_media"
        to_sign = f"folder={folder}&timestamp={timestamp}{api_secret}"
        signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

        url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
        data = {
            "api_key": api_key,
            "timestamp": timestamp,
            "folder": folder,
            "signature": signature
        }

        try:
            with open(file_obj, "rb") as f:
                files = {"file": (file_obj.name, f, "image/jpeg")}
                res = requests.post(url, data=data, files=files, timeout=(5, 30))

            if res.status_code == 200:
                res_json = res.json()
                secure_url = res_json.get("secure_url") or res_json.get("url")
                if secure_url and secure_url.startswith("https://"):
                    return {
                        "success": True,
                        "public_url": secure_url,
                        "provider": "cloudinary",
                        "public_id": res_json.get("public_id"),
                        "bytes": res_json.get("bytes")
                    }
                return {"success": False, "status": "no_secure_url", "error": "Cloudinary did not return a secure HTTPS URL."}
            else:
                err_msg = res.text
                try:
                    err_msg = res.json().get("error", {}).get("message", res.text)
                except Exception:
                    pass
                return {
                    "success": False,
                    "status": "cloudinary_error",
                    "error": f"Cloudinary upload failed (HTTP {res.status_code}): {err_msg[:200]}"
                }
        except Exception as e:
            logger.exception("Cloudinary upload failed")
            return {"success": False, "status": "upload_exception", "error": f"Failed uploading to Cloudinary: {str(e)}"}

    @classmethod
    def _resolve_custom_url(cls, file_obj: Path) -> Dict[str, Any]:
        base_url = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
        gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()
        try:
            rel = file_obj.resolve().relative_to(gen_dir)
            clean_rel = str(rel).replace("\\", "/")
            public_url = f"{base_url}/{clean_rel}"
            return {
                "success": True,
                "public_url": public_url,
                "provider": "custom_url"
            }
        except ValueError:
            return {
                "success": False,
                "status": "path_error",
                "error": "File does not reside inside the generated directory tree."
            }

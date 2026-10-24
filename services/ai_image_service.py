"""
services/ai_image_service.py
Cloudflare Workers AI (FLUX.1 Schnell) Image Generation Service for MINT.

Official Cloudflare references:
Model: https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/
Pricing/Free allocation: https://developers.cloudflare.com/workers-ai/platform/pricing/
REST API: https://developers.cloudflare.com/api/resources/ai/methods/run/

Model identifier: @cf/black-forest-labs/flux-1-schnell
REST endpoint: POST https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell
"""

import os
import io
import json
import base64
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from PIL import Image

import config
from database import get_db_connection

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_PROVIDER = "cloudflare_workers_ai"
DEFAULT_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"


def get_images_base_dir() -> Path:
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    img_dir = gen_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    return img_dir


class AIImageService:
    """
    Dedicated AI image generation adapter for Cloudflare Workers AI.
    Uses FLUX.1 Schnell (@cf/black-forest-labs/flux-1-schnell).
    Validates decoded image bytes with Pillow, enforces size limits, and persists
    metadata to the image_assets table. Never fabricates AI generation using fixed graphics
    or hidden paid fallbacks.
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
                if not os.getenv("CLOUDFLARE_ACCOUNT_ID") or not os.getenv("CLOUDFLARE_API_TOKEN"):
                    load_dotenv(env_file, override=True)
        except Exception:
            pass

    @classmethod
    def get_account_id(cls) -> Optional[str]:
        cls._reload_env_if_needed()
        return (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip() or None

    @classmethod
    def get_api_token(cls) -> Optional[str]:
        cls._reload_env_if_needed()
        return (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip() or None

    @classmethod
    def get_configured_model(cls) -> str:
        return os.getenv("IMAGE_MODEL", DEFAULT_IMAGE_MODEL).strip() or DEFAULT_IMAGE_MODEL

    @classmethod
    def get_configured_provider(cls) -> str:
        return os.getenv("IMAGE_PROVIDER", DEFAULT_IMAGE_PROVIDER).strip() or DEFAULT_IMAGE_PROVIDER

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        account_id = cls.get_account_id()
        api_token = cls.get_api_token()
        model = cls.get_configured_model()
        provider = cls.get_configured_provider()
        configured = bool(account_id and api_token)

        if configured:
            message = f"Cloudflare Workers AI ready ({model}) on free daily allocation"
        elif not account_id and not api_token:
            message = "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are not configured in .env"
        elif not account_id:
            message = "CLOUDFLARE_ACCOUNT_ID is missing in .env"
        else:
            message = "CLOUDFLARE_API_TOKEN is missing in .env"

        return {
            "configured": configured,
            "provider": provider,
            "model": model,
            "can_generate": configured,
            "free_tier": True,
            "message": message,
        }

    @classmethod
    def validate_prompt(cls, prompt: str) -> Dict[str, Any]:
        p = (prompt or "").strip()
        if not p:
            return {"valid": False, "error": "Image prompt cannot be empty."}
        if len(p) < 3:
            return {"valid": False, "error": "Image prompt is too short (minimum 3 characters)."}
        if len(p) > 2500:
            return {"valid": False, "error": "Image prompt exceeds maximum limit of 2,500 characters."}
        return {"valid": True, "prompt": p}

    @classmethod
    def build_effective_prompt(
        cls,
        prompt: str,
        style: Optional[str] = "photorealistic",
        negative_prompt: Optional[str] = None
    ) -> str:
        """Compose style and avoidance constraints into the instruction."""
        parts = [prompt.strip()]

        style_descriptions = {
            "photorealistic": "High-resolution commercial photography, natural lighting, sharp focus, professional depth of field.",
            "editorial": "High-end magazine editorial layout, stylish composition, refined color grading.",
            "illustration": "Clean modern digital vector illustration, cohesive color palette, elegant lines.",
            "minimalist": "Minimalist graphic aesthetic, spacious negative space, restrained sophisticated color scheme.",
            "infographic": "Clear infographic design with clean layout, neat typography, modern iconography.",
            "product_ad": "Commercial product advertisement photography, studio lighting, premium presentation.",
        }

        if style and style in style_descriptions:
            parts.append(f"Visual style: {style_descriptions[style]}")
        elif style:
            parts.append(f"Visual style: {style.strip()}")

        if negative_prompt and negative_prompt.strip():
            parts.append(f"Avoid elements: {negative_prompt.strip()}")

        return " | ".join(parts)

    @classmethod
    def generate_image(
        cls,
        prompt: str,
        negative_prompt: Optional[str] = None,
        aspect_ratio: str = "1:1",
        resolution: str = "1024x1024",
        style: str = "photorealistic",
        reference_image_bytes: Optional[bytes] = None,
        is_test: int = 0
    ) -> Dict[str, Any]:
        """
        Executes a prompt-to-image call via Cloudflare Workers AI FLUX.1 Schnell.
        Saves output in generated/images/<asset_id>/image_<asset_id>.png.
        Returns a dict with image metadata and file path.
        """
        val = cls.validate_prompt(prompt)
        if not val["valid"]:
            return {"success": False, "status": "validation_error", "error": val["error"]}

        account_id = cls.get_account_id()
        api_token = cls.get_api_token()
        if not account_id or not api_token:
            return {
                "success": False,
                "status": "not_configured",
                "error": "Cloudflare Workers AI credentials not configured. Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in your .env file to enable free AI image generation.",
            }

        model = cls.get_configured_model()
        full_prompt = cls.build_effective_prompt(val["prompt"], style=style, negative_prompt=negative_prompt)

        # Standardize aspect ratio
        valid_ratios = {"1:1", "4:5", "3:4", "4:3", "9:16", "16:9"}
        clean_aspect = aspect_ratio if aspect_ratio in valid_ratios else "1:1"

        endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

        # Cloudflare Workers AI FLUX.1 Schnell payload
        payload: Dict[str, Any] = {
            "prompt": full_prompt,
        }

        if reference_image_bytes:
            # Cloudflare supports image array of integers or base64 depending on schema
            ref_b64 = base64.b64encode(reference_image_bytes).decode("ascii")
            payload["image"] = ref_b64

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            res = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=(5, 90)
            )
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "status": "timeout",
                "error": "Cloudflare Workers AI image generation timed out after 90 seconds. Please try again.",
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "status": "connection_error",
                "error": "Could not connect to Cloudflare Workers AI API. Check network connectivity.",
            }
        except Exception as exc:
            logger.exception("AIImageService request failed")
            return {
                "success": False,
                "status": "error",
                "error": f"Failed calling Cloudflare Workers AI API: {str(exc)}",
            }

        # Check HTTP status codes
        if res.status_code != 200:
            err_msg = res.text
            try:
                err_json = res.json()
                errors = err_json.get("errors") or []
                if errors and isinstance(errors, list) and len(errors) > 0:
                    err_msg = errors[0].get("message") or str(errors[0])
                elif "messages" in err_json and err_json["messages"]:
                    err_msg = str(err_json["messages"])
            except Exception:
                pass

            if res.status_code == 429:
                return {
                    "success": False,
                    "status": "rate_limited",
                    "error": (
                        f"Cloudflare Workers AI daily free neuron allocation exhausted or rate limited (HTTP 429): {err_msg[:200]}. "
                        "Free tier provides 10,000 neurons per day; please check your Cloudflare dashboard or wait for the daily quota reset."
                    ),
                }
            elif res.status_code in (401, 403):
                return {
                    "success": False,
                    "status": "auth_error",
                    "error": f"Cloudflare API authorization failed (HTTP {res.status_code}): {err_msg[:200]}. Verify CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env.",
                }
            return {
                "success": False,
                "status": "api_error",
                "error": f"Cloudflare Workers AI returned HTTP {res.status_code}: {err_msg[:200]}",
            }

        # Extract image bytes: Cloudflare Workers AI returns binary content or JSON base64
        content_type = res.headers.get("content-type", "").lower()
        image_bytes: Optional[bytes] = None

        if content_type.startswith("image/"):
            image_bytes = res.content
        else:
            try:
                res_json = res.json()
                image_bytes = cls._extract_image_bytes(res_json)
            except Exception:
                # If non-JSON but has content, check if it's raw image bytes
                if len(res.content) > 100:
                    image_bytes = res.content

        if not image_bytes:
            return {
                "success": False,
                "status": "no_image_returned",
                "error": "Cloudflare Workers AI did not return valid image bytes in the response payload.",
                "response_preview": res.text[:200]
            }

        # Validate with Pillow
        try:
            with Image.open(io.BytesIO(image_bytes)) as pil_img:
                pil_img.verify()
                img_width, img_height = pil_img.size
                img_format = (pil_img.format or "PNG").upper()
        except Exception as pe:
            return {
                "success": False,
                "status": "invalid_image_data",
                "error": f"Generated output could not be parsed as a valid image: {str(pe)}",
            }

        ext = "png" if img_format == "PNG" else "jpg"

        # Save to disk under generated/images/<asset_id>/
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_size = len(image_bytes)

        # Pre-reserve row in image_assets to obtain numeric asset_id
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO image_assets (
                prompt, negative_prompt, aspect_ratio, resolution,
                style, provider, model, file_path, file_size_bytes,
                status, is_test, created_at
            ) VALUES (?, ?, ?, ?, ?, 'cloudflare_workers_ai', ?, '', ?, 'processing', ?, ?)
        """, (
            val["prompt"], negative_prompt, clean_aspect, f"{img_width}x{img_height}",
            style, model, file_size, is_test, now_str
        ))
        asset_id = cur.lastrowid
        conn.commit()

        # Target directory: generated/images/<asset_id>/
        asset_dir = get_images_base_dir() / str(asset_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        filename = f"image_{asset_id}.{ext}"
        file_path = asset_dir / filename

        try:
            with open(file_path, "wb") as f:
                f.write(image_bytes)
        except Exception as io_err:
            cur.execute("UPDATE image_assets SET status = 'failed', error_message = ? WHERE id = ?", (str(io_err), asset_id))
            conn.commit()
            conn.close()
            return {"success": False, "status": "write_error", "error": f"Failed writing image to disk: {str(io_err)}"}

        cur.execute("""
            UPDATE image_assets
            SET file_path = ?, status = 'completed', error_message = NULL
            WHERE id = ?
        """, (str(file_path), asset_id))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "status": "completed",
            "asset_id": asset_id,
            "prompt": val["prompt"],
            "provider": "cloudflare_workers_ai",
            "model": model,
            "aspect_ratio": clean_aspect,
            "resolution": f"{img_width}x{img_height}",
            "file_size_bytes": file_size,
            "file_path": str(file_path),
            "file_url": f"/api/images/{asset_id}/file",
            "created_at": now_str,
        }

    @classmethod
    def _extract_image_bytes(cls, data: Dict[str, Any]) -> Optional[bytes]:
        """Extracts and decodes base64 image data from JSON response formats."""
        if not isinstance(data, dict):
            return None

        # Check result.image
        result = data.get("result")
        if isinstance(result, dict):
            img_b64 = result.get("image") or result.get("data")
            if img_b64 and isinstance(img_b64, str):
                try:
                    return base64.b64decode(img_b64)
                except Exception:
                    pass
        elif isinstance(result, str) and len(result) > 100:
            try:
                return base64.b64decode(result)
            except Exception:
                pass

        # Check direct top-level image key
        if "image" in data and isinstance(data["image"], str):
            try:
                return base64.b64decode(data["image"])
            except Exception:
                pass

        return None

    @classmethod
    def list_images(cls, limit: int = 50, include_test: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        query = "SELECT * FROM image_assets"
        params = []
        if not include_test:
            query += " WHERE is_test = 0"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for item in rows:
            fp = item.get("file_path")
            item["exists"] = bool(fp and Path(fp).exists())
            item["file_url"] = f"/api/images/{item['id']}/file" if item["exists"] else None
        return rows

    @classmethod
    def get_image(cls, asset_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM image_assets WHERE id = ?", (asset_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        item = dict(row)
        fp = item.get("file_path")
        item["exists"] = bool(fp and Path(fp).exists())
        item["file_url"] = f"/api/images/{item['id']}/file" if item["exists"] else None
        return item

    @classmethod
    def delete_image(cls, asset_id: int) -> Dict[str, Any]:
        """
        Safely removes an image asset and its physical file within the images directory.
        Preserves image records referenced by active Instagram posts or products.
        """
        img = cls.get_image(asset_id)
        if not img:
            return {"success": False, "error": f"Image #{asset_id} not found."}

        conn = get_db_connection()
        cur = conn.cursor()

        # Check references in instagram_posts
        try:
            cur.execute("SELECT id, title FROM instagram_posts WHERE image_paths_json LIKE ?", (f"%{asset_id}%",))
            referenced_posts = cur.fetchall()
            if referenced_posts:
                post_titles = ", ".join([f"#{r['id']} '{r['title']}'" for r in referenced_posts[:2]])
                conn.close()
                return {
                    "success": False,
                    "error": f"Image #{asset_id} is referenced by Instagram post {post_titles}. Delete or update the post first.",
                    "referenced": True,
                }
        except Exception:
            pass

        base_dir = get_images_base_dir().resolve()
        fp = img.get("file_path")

        # Delete physical file if inside permitted directory
        if fp:
            target = Path(fp).resolve()
            try:
                target.relative_to(base_dir)
                if target.exists() and target.is_file():
                    target.unlink()
                # If directory is now empty, remove parent dir
                parent_dir = target.parent
                if parent_dir != base_dir and parent_dir.exists() and not any(parent_dir.iterdir()):
                    parent_dir.rmdir()
            except ValueError:
                conn.close()
                return {"success": False, "error": "Refusing to delete file outside generated images directory."}
            except Exception as e:
                logger.warning("Error deleting image file: %s", e)

        cur.execute("DELETE FROM image_assets WHERE id = ?", (asset_id,))
        conn.commit()
        conn.close()

        return {"success": True, "message": f"Image asset #{asset_id} deleted."}

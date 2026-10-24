"""
services/instagram_marketing_service.py
Instagram Product Marketing Engine for MINT.

Generates product-led marketing campaigns (single image or multi-slide carousels)
strictly derived from actual database records in `digital_products`.
Produces factual marketing copy, visual image prompts, editable hashtags, and
calls to action. Generates AI visuals using AIImageService and handles publication
through InstagramService after explicit user confirmation.
"""

import os
import io
import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

import config
from database import get_db_connection
from services.ai_service import AIService
from services.ai_image_service import AIImageService
from services.social_service import InstagramService
from services.media_hosting_service import MediaHostingService

logger = logging.getLogger(__name__)


def get_instagram_content_dir() -> Path:
    gen_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    base = gen_dir / "content" / "instagram"
    base.mkdir(parents=True, exist_ok=True)
    return base


class InstagramMarketingService:
    """
    Coordinates Instagram marketing content creation and publishing workflows.
    """

    @classmethod
    def get_eligible_products(cls) -> List[Dict[str, Any]]:
        """
        Loads non-test digital products from the database and checks their marketing readiness.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM digital_products WHERE is_test = 0 AND status != 'archived' ORDER BY id DESC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for p in rows:
            fp = p.get("file_path") or p.get("pdf_path")
            has_deliverable = bool(fp and Path(fp).exists() and Path(fp).stat().st_size > 0)
            p["has_deliverable"] = has_deliverable

            has_destination = bool(
                p.get("gumroad_url")
                or (p.get("gumroad_id") and p.get("gumroad_publish_status") == "published")
            )
            p["has_destination"] = has_destination

            # Ready for live purchase marketing if has deliverable and active destination
            p["is_marketable_live"] = has_deliverable and has_destination
            if not has_deliverable:
                p["readiness_note"] = "Missing physical deliverable file; draft preview only."
            elif not has_destination:
                p["readiness_note"] = "Missing verified Gumroad/public sales URL; draft preview only."
            else:
                p["readiness_note"] = "Ready for live marketing."

        return rows

    @classmethod
    def generate_marketing_post(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates an Instagram product marketing draft and AI images.
        """
        product_id = payload.get("product_id")
        if not product_id:
            return {"success": False, "error": "A valid digital product must be selected."}

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM digital_products WHERE id = ?", (product_id,))
        prod_row = cur.fetchone()
        conn.close()

        if not prod_row:
            return {"success": False, "error": f"Digital product #{product_id} not found."}

        prod = dict(prod_row)
        title = prod.get("title", "Untitled Product")
        audience = payload.get("audience") or prod.get("audience", "Solopreneurs & Creators")
        marketing_angle = payload.get("marketing_angle", "practical_benefits")
        visual_style = payload.get("visual_style", "editorial")
        aspect_ratio = payload.get("aspect_ratio", "1:1")
        post_type = payload.get("post_type", "single")  # 'single' or 'carousel'
        extra_instructions = (payload.get("extra_instructions") or "").strip()
        include_brand_logo = bool(payload.get("include_brand_logo", False))
        show_product_info = bool(payload.get("show_product_info", True))
        is_test = int(payload.get("is_test", 0))

        # Check product readiness
        fp = prod.get("file_path") or prod.get("pdf_path")
        has_deliverable = bool(fp and Path(fp).exists() and Path(fp).stat().st_size > 0)
        has_destination = bool(
            prod.get("gumroad_url")
            or (prod.get("gumroad_id") and prod.get("gumroad_publish_status") == "published")
        )

        readiness_warning = None
        if not has_deliverable or not has_destination:
            missing = []
            if not has_deliverable:
                missing.append("verified deliverable file")
            if not has_destination:
                missing.append("verified public Gumroad destination")
            readiness_warning = (
                f"Product is missing {', '.join(missing)}. "
                "Generated as a draft preview; not ready for active purchase promotion."
            )

        # Generate copy, hashtags, and CTA
        copy_data = cls._generate_copy(
            product=prod,
            audience=audience,
            angle=marketing_angle,
            post_type=post_type,
            has_destination=has_destination,
            custom_instructions=extra_instructions,
            custom_caption=payload.get("caption"),
            custom_hashtags=payload.get("hashtags"),
            custom_cta=payload.get("cta")
        )

        caption = copy_data["caption"]
        hashtags = copy_data["hashtags"]
        cta = copy_data["cta"]

        # Insert preliminary record in instagram_posts
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO instagram_posts (
                product_id, post_type, title, caption, hashtags, cta,
                image_paths_json, hosted_urls_json, target_audience,
                marketing_angle, visual_style, aspect_ratio,
                include_brand_logo, show_product_info, status, is_test,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?, ?, ?, 'generating_image', ?, ?, ?)
        """, (
            product_id, post_type, f"Marketing: {title[:80]}",
            caption, hashtags, cta, audience, marketing_angle,
            visual_style, aspect_ratio, int(include_brand_logo),
            int(show_product_info), is_test, now_str, now_str
        ))
        post_id = cur.lastrowid
        conn.commit()

        # Target directory: generated/content/instagram/<post_id>/
        post_dir = get_instagram_content_dir() / str(post_id)
        post_dir.mkdir(parents=True, exist_ok=True)

        # Determine number of slides
        slide_count = int(payload.get("slide_count", 3)) if post_type == "carousel" else 1
        slide_count = max(2, min(5, slide_count)) if post_type == "carousel" else 1

        image_paths = []
        gen_errors = []

        for i in range(1, slide_count + 1):
            slide_prompt = cls._compose_image_prompt(
                product=prod,
                slide_num=i,
                total_slides=slide_count,
                visual_style=visual_style,
                angle=marketing_angle,
                extra=extra_instructions
            )

            # Generate image via AIImageService
            res = AIImageService.generate_image(
                prompt=slide_prompt,
                aspect_ratio=aspect_ratio,
                style=visual_style,
                is_test=is_test
            )

            slide_dest = post_dir / f"slide_{i}.jpg"

            if res.get("success") and res.get("file_path") and Path(res["file_path"]).exists():
                src_path = Path(res["file_path"])
                # Apply optional typography or branding overlay if requested
                final_img = cls._apply_card_overlay(
                    src_image_path=src_path,
                    product_title=title,
                    price=prod.get("price"),
                    currency=prod.get("currency", "USD"),
                    show_info=show_product_info,
                    include_brand=include_brand_logo,
                    slide_num=i if slide_count > 1 else None,
                    total_slides=slide_count if slide_count > 1 else None
                )
                final_img.save(slide_dest, format="JPEG", quality=92)
                image_paths.append(str(slide_dest))
            else:
                gen_errors.append(f"Slide {i}: {res.get('error', 'AI image generation failed')}")

        if not image_paths:
            cur.execute("""
                UPDATE instagram_posts
                SET status = 'failed', error_message = ?, updated_at = ?
                WHERE id = ?
            """, ("; ".join(gen_errors), now_str, post_id))
            conn.commit()
            conn.close()
            return {
                "success": False,
                "status": "failed",
                "error": f"Failed to generate marketing images: {'; '.join(gen_errors)}",
                "post_id": post_id
            }

        # Status: awaiting review
        final_status = "awaiting_review"
        cur.execute("""
            UPDATE instagram_posts
            SET image_paths_json = ?, status = ?, error_message = ?, updated_at = ?
            WHERE id = ?
        """, (json.dumps(image_paths), final_status, readiness_warning, now_str, post_id))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "status": final_status,
            "post_id": post_id,
            "product_id": product_id,
            "post_type": post_type,
            "title": title,
            "caption": caption,
            "hashtags": hashtags,
            "cta": cta,
            "image_urls": [f"/api/instagram/content/{post_id}/files/{Path(p).name}" for p in image_paths],
            "readiness_warning": readiness_warning,
            "slide_count": len(image_paths)
        }

    @classmethod
    def _generate_copy(
        cls,
        product: Dict[str, Any],
        audience: str,
        angle: str,
        post_type: str,
        has_destination: bool,
        custom_instructions: str = "",
        custom_caption: Optional[str] = None,
        custom_hashtags: Optional[str] = None,
        custom_cta: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Generates grounded, non-hallucinatory caption and hashtags based on actual product data.
        """
        title = product.get("title", "")
        value_prop = product.get("value_proposition", "")
        desc = product.get("description", "")
        price = product.get("price", 14.99)
        currency = product.get("currency", "USD")

        # Call to action
        if custom_cta and custom_cta.strip():
            cta = custom_cta.strip()
        elif has_destination:
            cta = "Find it through the link in bio for instant access."
        else:
            cta = "Coming soon to the MINT library. Save this post to stay notified."

        # Hashtags
        if custom_hashtags and custom_hashtags.strip():
            hashtags = custom_hashtags.strip()
        else:
            hashtags = cls._derive_hashtags(product, audience, angle)

        # Caption
        if custom_caption and custom_caption.strip():
            caption = f"{custom_caption.strip()}\n\n{cta}\n\n{hashtags}"
            return {"caption": caption, "hashtags": hashtags, "cta": cta}

        # Build grounded caption using verified facts
        hook_lines = {
            "practical_benefits": f"A structured blueprint designed for {audience.lower()}.",
            "system_framework": f"Stop guessing your execution path. The {title} breaks down the exact workflow.",
            "curriculum_preview": f"Inside the {title}: actionable modules built for real execution.",
            "common_mistakes": f"The biggest hurdle {audience.lower()} face is lack of a unified system.",
        }
        hook = hook_lines.get(angle, f"Introducing {title}.")

        caption_body = (
            f"{hook}\n\n"
            f"{value_prop}\n\n"
            f"Key focus: {desc[:250]}\n\n"
            f"{cta}\n\n"
            f"{hashtags}"
        )

        return {"caption": caption_body, "hashtags": hashtags, "cta": cta}

    @classmethod
    def _derive_hashtags(cls, product: Dict[str, Any], audience: str, angle: str) -> str:
        """Derives clean, relevant hashtags without generic spam."""
        tags = set()

        # Category / Niche tags
        product_intent = product.get("product_intent") or product.get("product_type", "guide")
        intent_tag_map = {
            "fiction_story": ["#creativewriting", "#fictionreads", "#storytelling"],
            "non_fiction_guide": ["#productivityguide", "#executionframework", "#digitalassets"],
            "workbook_checklist": ["#workflowchecklist", "#actionabletemplates", "#plannercommunity"],
            "toolkit_template": ["#templatesystem", "#systemsbuilder", "#frameworks"],
            "guide": ["#practicalguide", "#digitaltools", "#entrepreneurship"]
        }
        for t in intent_tag_map.get(product_intent, ["#digitalblueprint", "#businesssystems"]):
            tags.add(t)

        # Audience-derived tags
        aud_clean = re.sub(r"[^\w\s]", "", audience.lower())
        for word in aud_clean.split():
            if len(word) > 4 and word not in {"general", "target", "their", "about"}:
                tags.add(f"#{word}")

        # Core venture tags
        tags.add("#mintengine")
        tags.add("#indiecreator")

        # Keep between 4 and 8 curated tags
        sorted_tags = sorted(list(tags))[:8]
        return " ".join(sorted_tags)

    @classmethod
    def _compose_image_prompt(
        cls,
        product: Dict[str, Any],
        slide_num: int,
        total_slides: int,
        visual_style: str,
        angle: str,
        extra: str = ""
    ) -> str:
        """Composes a factual, aesthetic image prompt based on verified product details."""
        title = product.get("title", "")
        intent = product.get("product_intent", "guide")

        if total_slides > 1:
            slide_focus = f"Slide {slide_num} of {total_slides} showcasing concept: {title}."
        else:
            slide_focus = f"Hero visual showcase for: {title}."

        prompt_elements = [
            f"Clean commercial aesthetic for digital asset: {title}.",
            slide_focus,
            f"Visual style: {visual_style} with balanced composition and premium studio feel."
        ]

        if extra:
            prompt_elements.append(f"Specific detail: {extra}")

        return " | ".join(prompt_elements)

    @classmethod
    def _apply_card_overlay(
        cls,
        src_image_path: Path,
        product_title: str,
        price: Optional[float],
        currency: str = "USD",
        show_info: bool = True,
        include_brand: bool = False,
        slide_num: Optional[int] = None,
        total_slides: Optional[int] = None
    ) -> Image.Image:
        """
        Subtle Pillow post-processing to overlay verified facts and branding on the AI-generated visual.
        """
        img = Image.open(src_image_path).convert("RGB")
        w, h = img.size
        draw = ImageDraw.Draw(img)

        # Slide indicator in top right for carousels
        if slide_num and total_slides:
            indicator_text = f"{slide_num}/{total_slides}"
            draw.rounded_rectangle([(w - 110, 40), (w - 40, 85)], radius=12, fill=(15, 23, 42))
            draw.text((w - 95, 52), indicator_text, fill=(255, 255, 255))

        # Brand badge in top left if requested
        if include_brand:
            draw.rounded_rectangle([(40, 40), (160, 85)], radius=12, fill=(79, 70, 229))  # MINT Purple
            draw.text((58, 52), "MINT", fill=(255, 255, 255))

        # Bottom info card if show_info is enabled
        if show_info:
            bar_height = 120
            # Semi-transparent dark scrim at bottom
            overlay = Image.new("RGBA", (w, bar_height), (15, 23, 42, 220))
            img.paste(overlay, (0, h - bar_height), overlay)

            draw = ImageDraw.Draw(img)
            # Verified Product Title
            draw.text((45, h - 95), product_title[:45], fill=(248, 250, 252))

            # Verified Price badge if known
            if price and price > 0:
                price_str = f"${price:.2f} {currency}"
                draw.text((45, h - 55), f"Official Release &middot; {price_str}", fill=(148, 163, 184))
            else:
                draw.text((45, h - 55), "Official MINT Digital Deliverable", fill=(148, 163, 184))

        return img

    @classmethod
    def publish_post(cls, post_id: int, confirmed: bool = False) -> Dict[str, Any]:
        """
        Publishes a prepared Instagram marketing post to Meta Graph API.
        Enforces:
        1. confirmed=True
        2. Media hosting check (uploads to public HTTPS host if local)
        3. Instagram account connection & permissions check
        4. Single or Carousel API call
        """
        if not confirmed:
            return {
                "success": False,
                "status": "confirmation_required",
                "error": "Instagram publishing requires explicit user confirmation. Set confirmed=True."
            }

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM instagram_posts WHERE id = ?", (post_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return {"success": False, "status": "not_found", "error": f"Post #{post_id} not found."}

        post = dict(row)
        caption = post.get("caption", "")
        post_type = post.get("post_type", "single")
        image_paths = []
        try:
            image_paths = json.loads(post.get("image_paths_json") or "[]")
        except Exception:
            pass

        if not image_paths:
            return {"success": False, "status": "no_images", "error": "This post does not contain generated images."}

        # Step A: Check media hosting readiness
        hosting_status = MediaHostingService.get_status()
        if not hosting_status.get("can_host"):
            return {
                "success": False,
                "status": "media_hosting_required",
                "error": hosting_status["message"],
                "setup_required": hosting_status.get("setup_required", [])
            }

        # Step B: Upload local images to public HTTPS media host
        hosted_urls = []
        for path_str in image_paths:
            upload_res = MediaHostingService.upload_image(path_str)
            if not upload_res.get("success") or not upload_res.get("public_url"):
                return {
                    "success": False,
                    "status": "media_upload_failed",
                    "error": f"Failed uploading media to public host: {upload_res.get('error', 'Unknown upload error')}"
                }
            hosted_urls.append(upload_res["public_url"])

        # Update hosted URLs in database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE instagram_posts SET hosted_urls_json = ? WHERE id = ?", (json.dumps(hosted_urls), post_id))
        conn.commit()
        conn.close()

        # Step C: Publish through InstagramService
        if post_type == "carousel" and len(hosted_urls) > 1:
            pub_res = InstagramService.publish_carousel(
                image_urls=hosted_urls,
                caption=caption,
                confirmed=True
            )
        else:
            pub_res = InstagramService.publish_media(
                media_url_or_path=hosted_urls[0],
                caption=caption,
                media_type="IMAGE",
                confirmed=True
            )

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cur = conn.cursor()

        if pub_res.get("success"):
            media_id = pub_res.get("media_id")
            cur.execute("""
                UPDATE instagram_posts
                SET status = 'published', media_id = ?, published_at = ?, error_message = NULL, updated_at = ?
                WHERE id = ?
            """, (media_id, now_str, now_str, post_id))
            conn.commit()
            conn.close()
            return {
                "success": True,
                "status": "published",
                "post_id": post_id,
                "media_id": media_id,
                "published_at": now_str,
                "message": f"Successfully published to Instagram! Media ID: {media_id}"
            }
        else:
            err = pub_res.get("error", "Publishing failed")
            cur.execute("""
                UPDATE instagram_posts
                SET status = 'failed', error_message = ?, updated_at = ?
                WHERE id = ?
            """, (err, now_str, post_id))
            conn.commit()
            conn.close()
            return {
                "success": False,
                "status": pub_res.get("status", "failed"),
                "error": err,
                "post_id": post_id
            }

    @classmethod
    def list_posts(cls, limit: int = 50, include_test: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        query = "SELECT * FROM instagram_posts"
        params = []
        if not include_test:
            query += " WHERE is_test = 0"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for item in rows:
            try:
                paths = json.loads(item.get("image_paths_json") or "[]")
                item["image_urls"] = [f"/api/instagram/content/{item['id']}/files/{Path(p).name}" for p in paths]
            except Exception:
                item["image_urls"] = []
        return rows

    @classmethod
    def get_post(cls, post_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM instagram_posts WHERE id = ?", (post_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        item = dict(row)
        try:
            paths = json.loads(item.get("image_paths_json") or "[]")
            item["image_urls"] = [f"/api/instagram/content/{item['id']}/files/{Path(p).name}" for p in paths]
        except Exception:
            item["image_urls"] = []
        return item

    @classmethod
    def delete_post(cls, post_id: int) -> Dict[str, Any]:
        """
        Deletes a local Instagram post record and its files.
        Warns if post was published on Meta that remote post cannot be removed automatically.
        """
        post = cls.get_post(post_id)
        if not post:
            return {"success": False, "error": f"Post #{post_id} not found."}

        is_published = post.get("status") == "published"
        media_id = post.get("media_id")

        # Safely remove post directory inside generated/content/instagram
        base_dir = get_instagram_content_dir().resolve()
        post_dir = (base_dir / str(post_id)).resolve()

        try:
            post_dir.relative_to(base_dir)
            if post_dir.exists() and post_dir.is_dir():
                for f in post_dir.iterdir():
                    if f.is_file():
                        f.unlink()
                post_dir.rmdir()
        except ValueError:
            return {"success": False, "error": "Path traversal check failed for post directory."}
        except Exception as e:
            logger.warning("Error removing post directory: %s", e)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM instagram_posts WHERE id = ?", (post_id,))
        conn.commit()
        conn.close()

        warning = None
        if is_published and media_id:
            warning = (
                f"Local post record removed. Note: Published Meta media (ID: {media_id}) "
                "remains live on Instagram and must be removed directly in the Instagram app."
            )

        return {
            "success": True,
            "message": f"Instagram post #{post_id} removed locally.",
            "warning": warning
        }

import uuid
from services.media_service import generate_promo_image, generate_short_video, generate_digital_guide

class CreatorAgent:
    """
    Synthesizes creative copy, structured digital products, and triggers local media assets
    (graphics via Pillow and vertical video renders via global FFmpeg).
    """
    def create_venture_assets(self, title: str, business_model: str, audience: str, custom_hook: str = "") -> dict:
        uid = uuid.uuid4().hex[:6]

        hook = custom_hook or f"Structured workflow blueprint engineered for {audience}."

        script = (
            f"[Visual: Clean workspace focus]\n"
            f"Host: '{hook}'\n"
            f"[Visual: Demonstration of structured system]\n"
            f"Host: 'Here is the step-by-step framework to organize your process.'\n"
            f"[Visual: Product breakdown overlay]\n"
            f"Host: 'Check the link below for the complete starter pack.'"
        )

        caption = f"{hook} #productivity #focus #entrepreneurship #mintengine"
        call_to_action = "Get the instant template download below"
        disclaimer = "Includes transparent affiliate partner referral links where noted." if business_model == "affiliate" else "Educational digital guide. Instant digital access."

        # Produce actual physical assets
        image_filename = f"asset_img_{uid}.png"
        video_filename = f"asset_vid_{uid}.mp4"
        guide_filename = f"product_guide_{uid}.md"

        img_path = generate_promo_image(title, hook, image_filename)
        vid_path = generate_short_video(title, hook, video_filename)

        guide_content = (
            f"## Overview\n{title} is designed specifically for {audience}.\n\n"
            f"### Key Steps\n"
            f"1. Audit daily recurring tasks.\n"
            f"2. Implement standardized repeatable checklists.\n"
            f"3. Review quantitative outputs weekly.\n\n"
            f"### Action Plan\nApply this template over a 7-day period to standardize execution."
        )
        doc_path = generate_digital_guide(title, guide_content, guide_filename)

        return {
            "title": title,
            "hook": hook,
            "script": script,
            "caption": caption,
            "call_to_action": call_to_action,
            "disclaimer": disclaimer,
            "image_path": img_path,
            "video_path": vid_path,
            "guide_path": doc_path,
            "price": 14.99 if business_model == "digital_product" else 9.99
        }

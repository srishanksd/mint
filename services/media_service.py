import subprocess
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import config

def _get_dir(category: str) -> Path:
    base = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated")
    d = base / category
    d.mkdir(parents=True, exist_ok=True)
    return d

def generate_promo_image(title: str, subtitle: str, filename: str) -> str:
    """Creates a clean promotional graphic locally without external APIs."""
    img_dir = _get_dir("images")
    out_path = img_dir / filename

    width, height = 1080, 1080
    image = Image.new("RGB", (width, height), color=(240, 243, 246))
    draw = ImageDraw.Draw(image)

    # Card background
    card_margin = 80
    draw.rounded_rectangle(
        [(card_margin, card_margin), (width - card_margin, height - card_margin)],
        radius=40,
        fill=(255, 255, 255),
        outline=(210, 215, 222),
        width=3
    )

    # Accent badge
    draw.rounded_rectangle([(140, 140), (460, 210)], radius=15, fill=(30, 41, 59))
    draw.text((160, 155), "MINT VENTURE ASSET", fill=(255, 255, 255))

    # Title & Subtitle
    draw.text((140, 320), title[:45], fill=(15, 23, 42))
    draw.text((140, 420), subtitle[:120], fill=(71, 85, 105))

    # Metric preview box
    draw.rounded_rectangle([(140, 680), (width - 140, 880)], radius=25, fill=(241, 245, 249))
    draw.text((170, 720), "OFFICIAL PILOT RELEASE * VERIFIED TESTING", fill=(100, 116, 139))
    draw.text((170, 780), "Structured Demonstration Unit", fill=(15, 23, 42))

    image.save(out_path, format="PNG")
    return str(out_path)

def generate_short_video(title: str, hook: str, filename: str) -> str:
    """Uses system ffmpeg to render a short vertical MP4 video."""
    vid_dir = _get_dir("videos")
    out_path = vid_dir / filename

    # Generate a background frame first
    img_dir = _get_dir("images")
    frame_name = f"temp_frame_{filename}.png"
    frame_path = img_dir / frame_name

    width, height = 1080, 1920
    frame = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(frame)

    # Inner Frame Container
    draw.rounded_rectangle([(60, 120), (width - 60, height - 120)], radius=30, fill=(30, 41, 59), outline=(51, 65, 85), width=4)

    # Header Badge
    draw.rounded_rectangle([(120, 200), (520, 280)], radius=15, fill=(79, 70, 229)) # MINT purple
    draw.text((150, 225), "OFFICIAL MINT RELEASE", fill=(255, 255, 255))

    # Clean Typography
    draw.text((120, 450), title[:30], fill=(248, 250, 252))
    draw.text((120, 600), hook[:100], fill=(203, 213, 225))

    # Call to action footer
    draw.rounded_rectangle([(120, height - 350), (width - 120, height - 220)], radius=20, fill=(17, 24, 39))
    draw.text((160, height - 300), "CHECK VERIFIED LINK BELOW", fill=(129, 140, 248))

    frame.save(frame_path, format="PNG")

    # Render a 5-second video from image loop
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(frame_path),
        "-c:v", "libx264",
        "-t", "5",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1080:1920",
        "-r", "30",
        "-an",
        str(out_path)
    ]

    try:
        subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    finally:
        if frame_path.exists():
            try:
                frame_path.unlink()
            except OSError:
                pass

    return str(out_path)

def generate_digital_guide(title: str, content: str, filename: str) -> str:
    """Saves structured markdown guide deliverable to disk."""
    prod_dir = _get_dir("products")
    doc_path = prod_dir / filename
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{content}")
    return str(doc_path)

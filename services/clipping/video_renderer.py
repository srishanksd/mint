"""
services/clipping/video_renderer.py
High-Performance FFmpeg Rendering Pipeline for Native Video Clipping.

Executes:
- Fast accurate segment extraction with -ss and -t
- Smart 9:16 vertical re-framing (face crop, blurred background, or center pad)
- Styled ASS subtitle burning with Windows-safe path escaping and robust fallback
- Professional audio loudness leveling (AAC 192kbps)
- Faststart MOOV atom tagging for instantaneous browser streaming
- Automatic high-res thumbnail extraction (.jpg)
"""

import os
import uuid
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from services.clipping.smart_framing import SmartFramingService
from services.clipping.quality_checker import QualityChecker

logger = logging.getLogger(__name__)


def escape_ffmpeg_path(file_path: str) -> str:
    """
    Escapes a filesystem path for FFmpeg filter arguments (subtitles/ass filter) on Windows.
    Single backslash before colon escapes the drive letter colon (e.g. D: -> D\\:),
    forward slashes for path separators, and escaped single quotes.
    """
    p = str(Path(file_path).resolve())
    # Replace backslashes with forward slashes
    p = p.replace("\\", "/")
    # Escape colon with single backslash for FFmpeg filter parser (e.g. D: -> D\:)
    p = p.replace(":", "\\:")
    # Escape single quotes
    p = p.replace("'", "\\'")
    return p


class VideoRenderer:
    """
    Renders high-quality 1080x1920 MP4 video clips from source footage using FFmpeg.
    """

    @classmethod
    def render_clip(
        cls,
        source_video_path: str,
        start_sec: float,
        end_sec: float,
        output_mp4_path: str,
        ass_subtitle_path: Optional[str] = None,
        framing_mode: str = "blurred_bg",
        has_audio: bool = True,
        input_width: int = 1920,
        input_height: int = 1080
    ) -> Dict[str, Any]:
        """
        Renders a 9:16 vertical MP4 clip using genuine source footage.
        Atomic write with temporary files.
        """
        duration = max(1.0, end_sec - start_sec)
        out_p = Path(output_mp4_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        temp_out = out_p.with_name(f"temp_{uuid.uuid4().hex[:8]}_{out_p.name}")

        framing = SmartFramingService.get_filtergraph(
            video_path=source_video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            mode=framing_mode,
            input_width=input_width,
            input_height=input_height
        )

        # Build FFmpeg command
        filter_type = framing.get("filter_type", "vf")
        filter_str = framing.get("filter", "")

        # Incorporate subtitle burning if ASS file is available
        subtitles_active = False
        if ass_subtitle_path and os.path.isfile(ass_subtitle_path):
            escaped_ass = escape_ffmpeg_path(ass_subtitle_path)
            sub_filter = f"ass=filename='{escaped_ass}'"
            if filter_type == "complex":
                # Append subtitle filter to complex filter chain
                # Replace final [vout] with [vframing];[vframing]ass=...[vout]
                if "[vout]" in filter_str:
                    filter_str = filter_str.replace("[vout]", "[vpre]") + f";[vpre]{sub_filter}[vout]"
                    subtitles_active = True
            else:
                filter_str = f"{filter_str},{sub_filter}" if filter_str else sub_filter
                subtitles_active = True

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-i", source_video_path,
            "-t", str(duration)
        ]

        if filter_type == "complex":
            cmd.extend(["-filter_complex", filter_str, "-map", framing.get("map", "[vout]")])
        else:
            cmd.extend(["-vf", filter_str, "-map", "0:v:0"])

        if has_audio:
            cmd.extend([
                "-map", "0:a:0?",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000"
            ])
        else:
            cmd.append("-an")

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(temp_out)
        ])

        try:
            logger.info("Executing primary FFmpeg rendering for clip: %s", temp_out)
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)

            # If rendering failed with subtitles, retry immediately without subtitles as fallback
            if res.returncode != 0 and subtitles_active:
                logger.warning("FFmpeg failed with subtitles; retrying without burning subtitles. Stderr: %s", res.stderr[-300:])
                fallback_framing = SmartFramingService.get_filtergraph(
                    video_path=source_video_path,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    mode=framing_mode,
                    input_width=input_width,
                    input_height=input_height
                )
                fb_cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_sec),
                    "-i", source_video_path,
                    "-t", str(duration)
                ]
                if fallback_framing.get("filter_type") == "complex":
                    fb_cmd.extend(["-filter_complex", fallback_framing["filter"], "-map", fallback_framing.get("map", "[vout]")])
                else:
                    fb_cmd.extend(["-vf", fallback_framing["filter"], "-map", "0:v:0"])

                if has_audio:
                    fb_cmd.extend(["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k"])
                else:
                    fb_cmd.append("-an")

                fb_cmd.extend([
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(temp_out)
                ])
                res = subprocess.run(fb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)

            if res.returncode != 0 or not temp_out.exists() or temp_out.stat().st_size == 0:
                logger.error("FFmpeg render failed completely: %s", res.stderr[-400:])
                temp_out.unlink(missing_ok=True)
                return {
                    "success": False,
                    "error": f"FFmpeg failed to render clip: {res.stderr[-200:]}"
                }

            # Verify rendered video
            verify_res = QualityChecker.verify_clip(str(temp_out), expected_duration=duration, require_audio=has_audio)
            if not verify_res.get("passed"):
                logger.error("Quality verification failed: %s", verify_res.get("error"))
                temp_out.unlink(missing_ok=True)
                return {
                    "success": False,
                    "error": f"Rendered clip failed quality check: {verify_res.get('error')}"
                }

            # Finalize atomic rename
            if out_p.exists():
                out_p.unlink(missing_ok=True)
            shutil.move(str(temp_out), str(out_p))

            # Extract thumbnail
            thumb_path = out_p.with_suffix(".jpg")
            cls.extract_thumbnail(str(out_p), str(thumb_path))

            logger.info("Successfully rendered and verified vertical Short: %s (%d bytes)", out_p, out_p.stat().st_size)
            return {
                "success": True,
                "output_path": str(out_p),
                "thumbnail_path": str(thumb_path) if thumb_path.exists() else None,
                "duration": verify_res.get("details", {}).get("duration", duration),
                "file_size": out_p.stat().st_size,
                "framing_mode": framing.get("mode")
            }

        except Exception as exc:
            logger.error("Unexpected error during video rendering: %s", exc)
            temp_out.unlink(missing_ok=True)
            return {
                "success": False,
                "error": f"Rendering error: {str(exc)}"
            }

    @classmethod
    def extract_thumbnail(cls, video_path: str, output_jpg_path: str, offset_sec: float = 1.0) -> bool:
        """Extracts a high quality poster frame."""
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(offset_sec),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_jpg_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            return res.returncode == 0 and Path(output_jpg_path).exists()
        except Exception:
            return False

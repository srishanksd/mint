"""
services/clipping/caption_generator.py
Dynamic ASS Subtitle Generator for High-Retention YouTube Shorts.

Generates Advanced SubStation Alpha (.ass) subtitles with:
- Word-by-word karaoke & active keyword highlights
- Safe vertical margins protecting against Shorts UI overlay occlusion
- High-contrast outlines and drop shadows
- Clean chunking (3-5 words per screen)
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def format_ass_time(seconds: float) -> str:
    """Formats seconds as H:MM:SS.cs for ASS subtitles."""
    sec_int = int(seconds)
    centis = int(round((seconds - sec_int) * 100))
    if centis >= 100:
        sec_int += 1
        centis = 0
    hrs = sec_int // 3600
    mins = (sec_int % 3600) // 60
    secs = sec_int % 60
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"


class CaptionGenerator:
    """
    Constructs styled ASS subtitle files from speech word timestamps.
    """

    ASS_HEADER_TEMPLATE = """[Script Info]
Title: MINT Native High-Retention Shorts Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,56,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4.5,2.0,2,60,60,340,1
Style: Highlight,Arial Black,56,&H0000FFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,105,105,0,0,1,5.0,2.0,2,60,60,340,1
Style: Clean,Arial,52,&H00FFFFFF,&H00CCCCCC,&H00000000,&H60000000,-1,0,0,0,100,100,0,0,1,3.0,1.5,2,60,60,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    @classmethod
    def generate_ass_subtitles(
        cls,
        segments: List[Dict[str, Any]],
        clip_start: float,
        clip_end: float,
        output_ass_path: str,
        style: str = "beast",
        max_words_per_line: int = 4
    ) -> Optional[str]:
        """
        Creates an ASS subtitle file aligned with the clip's local timeline (0.0 to duration).
        """
        clip_duration = clip_end - clip_start
        if clip_duration <= 0.0:
            return None

        out_p = Path(output_ass_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # Extract words falling inside [clip_start, clip_end]
        clip_words: List[Dict[str, Any]] = []
        for s in segments:
            words = s.get("words", [])
            if words:
                for w in words:
                    w_start = w["start"]
                    w_end = w["end"]
                    if w_end > clip_start and w_start < clip_end:
                        # Normalize time relative to clip start
                        local_start = max(0.0, w_start - clip_start)
                        local_end = min(clip_duration, w_end - clip_start)
                        if local_end > local_start:
                            clip_words.append({
                                "word": w["word"].strip(),
                                "start": local_start,
                                "end": local_end
                            })
            else:
                # Segment without word timestamps: distribute words evenly
                s_start = s["start"]
                s_end = s["end"]
                if s_end > clip_start and s_start < clip_end:
                    local_s_start = max(0.0, s_start - clip_start)
                    local_s_end = min(clip_duration, s_end - clip_start)
                    raw_words = s["text"].split()
                    if raw_words and (local_s_end > local_s_start):
                        step = (local_s_end - local_s_start) / len(raw_words)
                        for idx, rw in enumerate(raw_words):
                            w_st = local_s_start + (idx * step)
                            w_et = w_st + step
                            clip_words.append({
                                "word": rw,
                                "start": round(w_st, 2),
                                "end": round(w_et, 2)
                            })

        if not clip_words:
            # No dialogue in clip
            return None

        # Group words into chunks of 3 to 5 words
        chunks: List[List[Dict[str, Any]]] = []
        current_chunk: List[Dict[str, Any]] = []

        for w in clip_words:
            current_chunk.append(w)
            # Break chunk if max words reached or end punctuation encountered
            if len(current_chunk) >= max_words_per_line or w["word"].endswith((".", "!", "?")):
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            chunks.append(current_chunk)

        # Build ASS dialogue events
        events: List[str] = []
        style_name = "Clean" if style == "clean" else "Default"

        for chunk in chunks:
            chunk_start = chunk[0]["start"]
            chunk_end = chunk[-1]["end"]
            start_str = format_ass_time(chunk_start)
            end_str = format_ass_time(chunk_end)

            if style == "karaoke":
                # Karaoke line with active word highlighted per word slice
                for active_idx, active_word in enumerate(chunk):
                    w_st_str = format_ass_time(active_word["start"])
                    w_et_str = format_ass_time(active_word["end"])

                    line_parts = []
                    for idx, w in enumerate(chunk):
                        word_text = w["word"].upper()
                        if idx == active_idx:
                            # Yellow bold highlight for active spoken word
                            line_parts.append(f"{{\\c&H0000FFFF&\\fscx108\\fscy108}}{word_text}{{\\r}}")
                        else:
                            # White text
                            line_parts.append(f"{{\\c&H00FFFFFF&}}{word_text}")

                    display_line = " ".join(line_parts)
                    events.append(f"Dialogue: 0,{w_st_str},{w_et_str},{style_name},,0,0,0,,{display_line}")
            else:
                # Beast style: bold uppercase text with active first or emphasized word in yellow
                line_text = " ".join([w["word"].upper() for w in chunk])
                # Highlight punchy words
                for pw in ["HOW", "SECRET", "MONEY", "STOP", "NEVER", "BEST", "WHY", "MISTAKE", "HACK"]:
                    if pw in line_text:
                        line_text = line_text.replace(pw, f"{{\\c&H0000FFFF&}}{pw}{{\\r}}")
                events.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{line_text}")

        content = cls.ASS_HEADER_TEMPLATE + "\n".join(events) + "\n"

        try:
            with open(out_p, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Generated ASS subtitle file (%d events) at %s", len(events), out_p)
            return str(out_p)
        except Exception as exc:
            logger.error("Failed to write ASS subtitles to %s: %s", out_p, exc)
            return None

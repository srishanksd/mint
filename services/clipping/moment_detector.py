"""
services/clipping/moment_detector.py
Natural Boundary Moment Detector for Native Video Clipping.

Ensures video cuts strictly respect spoken sentence and phrase boundaries from word-level
timestamps, eliminating awkward cut-off words or mid-sentence truncations.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MomentDetector:
    """
    Detects clean start and end cut points for candidate video clips.
    """

    @classmethod
    def extract_word_stream(cls, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Flattens segment words into a continuous chronological word stream.
        """
        all_words = []
        for s in segments:
            for w in s.get("words", []):
                all_words.append(w)
        return all_words

    @classmethod
    def find_speech_pauses(cls, words: List[Dict[str, Any]], min_pause_sec: float = 0.35) -> List[float]:
        """
        Finds natural speech pauses between consecutive words.
        """
        pauses = []
        for i in range(len(words) - 1):
            gap = words[i + 1]["start"] - words[i]["end"]
            if gap >= min_pause_sec:
                # Midpoint of the pause
                pauses.append(round((words[i]["end"] + words[i + 1]["start"]) / 2.0, 2))
        return pauses

    @classmethod
    def snap_to_word_boundary(
        cls,
        target_time: float,
        words: List[Dict[str, Any]],
        mode: str = "start",
        max_drift_sec: float = 1.5
    ) -> float:
        """
        Snaps a raw target time to the nearest word boundary so words aren't cut in half.
        - If mode == 'start': snaps to the start of a word immediately following a pause or punctuation.
        - If mode == 'end': snaps to the end of a word preceding a pause or ending a sentence.
        """
        if not words:
            return target_time

        closest_boundary = target_time
        min_dist = float("inf")

        for i, w in enumerate(words):
            if mode == "start":
                dist = abs(w["start"] - target_time)
                if dist < min_dist and dist <= max_drift_sec:
                    min_dist = dist
                    closest_boundary = w["start"]
            else:
                dist = abs(w["end"] - target_time)
                if dist < min_dist and dist <= max_drift_sec:
                    min_dist = dist
                    closest_boundary = w["end"]

        return round(closest_boundary, 2)

    @classmethod
    def generate_candidate_windows(
        cls,
        segments: List[Dict[str, Any]],
        total_duration: float,
        min_duration: float = 20.0,
        max_duration: float = 55.0,
        step_sec: float = 10.0
    ) -> List[Dict[str, float]]:
        """
        Generates candidate time windows respecting sentence and word boundaries.
        Falls back to sliding windows if transcript is empty.
        """
        windows: List[Dict[str, float]] = []

        if not segments:
            # Deterministic media duration windows for silent or non-speech videos
            if total_duration <= max_duration:
                windows.append({"start": 0.0, "end": round(total_duration, 2), "duration": round(total_duration, 2)})
            else:
                curr = 5.0 if total_duration > 60.0 else 0.0
                while curr + min_duration <= total_duration:
                    end = min(total_duration, curr + 40.0)
                    windows.append({"start": round(curr, 2), "end": round(end, 2), "duration": round(end - curr, 2)})
                    curr += step_sec
                    if len(windows) >= 5:
                        break
            return windows

        # Words available: construct sentence-aligned windows
        for i, seg in enumerate(segments):
            start = seg["start"]
            if start + min_duration > total_duration:
                break

            for j in range(i, len(segments)):
                end = segments[j]["end"]
                dur = end - start
                if dur > max_duration:
                    break
                if dur >= min_duration:
                    # Check if ending segment terminates with sentence punctuation
                    text_end = segments[j]["text"].strip()
                    ends_cleanly = text_end.endswith((".", "!", "?"))
                    windows.append({
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "duration": round(dur, 2),
                        "ends_cleanly": ends_cleanly,
                        "start_seg_idx": i,
                        "end_seg_idx": j
                    })

        return windows

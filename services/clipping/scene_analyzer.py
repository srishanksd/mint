"""
services/clipping/scene_analyzer.py
Visual Scene Cut and Transition Analyzer using OpenCV.

Detects shot boundaries and allows video cut points to align cleanly with visual transitions,
preventing awkward flash cuts or truncated camera angles.
"""

import os
import logging
from typing import List, Optional
import cv2

logger = logging.getLogger(__name__)


class SceneAnalyzer:
    """
    Detects visual shot changes in video using OpenCV frame differences.
    """

    @classmethod
    def detect_scene_cuts(
        cls,
        video_path: str,
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        threshold: float = 32.0,
        max_samples: int = 40
    ) -> List[float]:
        """
        Samples key frames strategically across the window and detects sudden color/intensity shifts
        indicating visual scene transitions, avoiding heavy seeking on large files.
        """
        scene_cuts: List[float] = []
        if not video_path or not os.path.isfile(video_path):
            return scene_cuts

        # For large source video files (>30MB), speech word timestamps provide microsecond-accurate
        # cut points; skip heavy video decoding to keep rendering blazing fast.
        try:
            if os.path.getsize(video_path) > 30 * 1024 * 1024:
                return scene_cuts
        except Exception:
            pass

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return scene_cuts

            native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            native_dur = total_frames / native_fps if native_fps > 0 else 0.0

            effective_end = min(native_dur, end_sec) if end_sec else native_dur
            duration = max(1.0, effective_end - start_sec)

            num_points = min(max_samples, int(duration * 2))
            if num_points <= 1:
                cap.release()
                return scene_cuts

            step_sec = duration / num_points
            prev_gray = None

            for i in range(num_points):
                t = start_sec + (i * step_sec)
                target_frame = int(t * native_fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if not ret:
                    break

                small = cv2.resize(frame, (80, 45))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    mean_diff = float(diff.mean())
                    if mean_diff >= threshold:
                        scene_cuts.append(round(t, 2))

                prev_gray = gray

            cap.release()
            logger.debug("Detected %d scene transitions in %s", len(scene_cuts), video_path)

        except Exception as exc:
            logger.warning("Scene cut detection failed on %s: %s", video_path, exc)

        return scene_cuts

    @classmethod
    def snap_to_scene(
        cls,
        cut_time: float,
        scene_cuts: List[float],
        max_drift_sec: float = 0.4
    ) -> float:
        """
        Snaps a cut time to the closest visual scene transition if within max_drift_sec.
        """
        if not scene_cuts:
            return cut_time

        closest = cut_time
        min_dist = float("inf")

        for sc in scene_cuts:
            dist = abs(sc - cut_time)
            if dist < min_dist and dist <= max_drift_sec:
                min_dist = dist
                closest = sc

        return round(closest, 2)

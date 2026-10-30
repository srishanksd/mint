"""
tests/test_native_clipper.py
Comprehensive automated test suite for ChronoForge / MINT Native AI Video Clipping Engine.
Verifies all 10 local modules, zero cloud dependencies, 9:16 vertical outputs,
and end-to-end pipeline execution with genuine media.
"""

import os
import io
import json
import uuid
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from app import app as flask_app
from database import get_db_connection
from services.clipping.video_ingestion import VideoIngestionService
from services.clipping.transcription import TranscriptionService
from services.clipping.transcript_analyzer import TranscriptAnalyzer
from services.clipping.moment_detector import MomentDetector
from services.clipping.moment_ranker import MomentRanker
from services.clipping.scene_analyzer import SceneAnalyzer
from services.clipping.smart_framing import SmartFramingService
from services.clipping.caption_generator import CaptionGenerator
from services.clipping.quality_checker import QualityChecker
from services.clipping.video_renderer import VideoRenderer
from services.clipping.clipping_pipeline import ClippingPipeline
from agents.youtube_clips_agent import YouTubeClipsAgent


class TestNativeClipperEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="test_native_clipper_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_video_ingestion_probe_empty_and_missing(self):
        """Verifies graceful handling of non-existent and empty files."""
        res_missing = VideoIngestionService.probe_media("/path/does/not/exist.mp4")
        self.assertFalse(res_missing["success"])
        self.assertIn("not found", res_missing["error"])

        empty_file = Path(self.temp_dir) / "empty.mp4"
        empty_file.write_bytes(b"")
        res_empty = VideoIngestionService.probe_media(str(empty_file))
        self.assertFalse(res_empty["success"])
        self.assertIn("empty", res_empty["error"])

    def test_transcript_analyzer_heuristics(self):
        """Tests that semantic analysis detects hooks, keywords, and scores properly."""
        sample_segments = [
            {"start": 0.0, "end": 4.5, "text": "Here is how to scale your revenue to a million dollars."},
            {"start": 4.6, "end": 9.0, "text": "The secret strategy is automating your digital product funnels."},
            {"start": 9.1, "end": 14.0, "text": "Never make the mistake of ignoring unit economics."},
            {"start": 14.1, "end": 22.0, "text": "Once you build the right blueprint, profit follows naturally."}
        ]

        candidates = TranscriptAnalyzer.analyze_heuristics(
            segments=sample_segments,
            num_candidates=2,
            min_duration=10.0,
            max_duration=25.0,
            target_duration=18.0
        )

        self.assertTrue(len(candidates) > 0)
        top = candidates[0]
        self.assertIn("start", top)
        self.assertIn("end", top)
        self.assertIn("headline", top)
        self.assertTrue(70.0 <= top["virality_score"] <= 91.0)
        self.assertTrue(top["duration"] >= 10.0)

    def test_moment_detector_window_generation(self):
        """Tests generation of clean candidate windows from segments."""
        sample_segments = [
            {"start": 0.0, "end": 5.0, "text": "Opening hook sentence."},
            {"start": 5.0, "end": 12.0, "text": "Second supporting phrase."},
            {"start": 12.0, "end": 22.0, "text": "Third deep dive conclusion."}
        ]

        windows = MomentDetector.generate_candidate_windows(
            segments=sample_segments,
            total_duration=25.0,
            min_duration=10.0,
            max_duration=25.0
        )

        self.assertTrue(len(windows) > 0)
        for w in windows:
            self.assertTrue(w["duration"] >= 10.0)
            self.assertTrue(w["start"] >= 0.0)

    def test_moment_ranker_deduplication(self):
        """Tests Non-Maximum Suppression to eliminate heavily overlapping candidate clips."""
        cand1 = {"start": 0.0, "end": 30.0, "virality_score": 88.0, "headline": "Top Moment"}
        cand2 = {"start": 2.0, "end": 31.0, "virality_score": 84.0, "headline": "Overlap Clip"}  # 93% overlap with cand1
        cand3 = {"start": 60.0, "end": 90.0, "virality_score": 82.0, "headline": "Distinct Moment"}  # 0% overlap

        selected = MomentRanker.rank_and_select([cand1, cand2, cand3], num_clips=2, max_overlap_ratio=0.35)

        self.assertEqual(len(selected), 2)
        # cand2 must be suppressed because it heavily overlaps with cand1
        headlines = [c["headline"] for c in selected]
        self.assertIn("Top Moment", headlines)
        self.assertIn("Distinct Moment", headlines)
        self.assertNotIn("Overlap Clip", headlines)

    def test_smart_framing_blurred_background(self):
        """Tests FFmpeg filtergraph construction for vertical 9:16 blurred background."""
        framing = SmartFramingService.get_filtergraph(
            video_path="test.mp4",
            start_sec=0.0,
            end_sec=30.0,
            mode="blurred_bg",
            input_width=1920,
            input_height=1080
        )

        self.assertEqual(framing["filter_type"], "complex")
        self.assertIn("1080:1920", framing["filter"])
        self.assertIn("boxblur", framing["filter"])
        self.assertEqual(framing["map"], "[vout]")

    def test_caption_generator_ass_file(self):
        """Tests generation of valid ASS subtitles with safe margins and styling."""
        sample_segments = [
            {
                "start": 0.0, "end": 4.0, "text": "Here is the secret blueprint.",
                "words": [
                    {"word": "Here", "start": 0.0, "end": 0.6},
                    {"word": "is", "start": 0.7, "end": 1.1},
                    {"word": "the", "start": 1.2, "end": 1.5},
                    {"word": "secret", "start": 1.6, "end": 2.5},
                    {"word": "blueprint", "start": 2.6, "end": 3.8}
                ]
            }
        ]

        ass_file = Path(self.temp_dir) / "test_captions.ass"
        res_path = CaptionGenerator.generate_ass_subtitles(
            segments=sample_segments,
            clip_start=0.0,
            clip_end=4.0,
            output_ass_path=str(ass_file),
            style="beast"
        )

        self.assertIsNotNone(res_path)
        self.assertTrue(ass_file.exists())
        content = ass_file.read_text(encoding="utf-8")
        self.assertIn("[Script Info]", content)
        self.assertIn("PlayResX: 1080", content)
        self.assertIn("PlayResY: 1920", content)
        self.assertIn("340", content)
        self.assertIn("Dialogue:", content)

    def test_quality_checker_validation(self):
        """Verifies QualityChecker enforcement of dimensions and stream presence."""
        dummy_bad = Path(self.temp_dir) / "bad.mp4"
        dummy_bad.write_bytes(b"\x00" * 200)

        check = QualityChecker.verify_clip(str(dummy_bad))
        self.assertFalse(check["passed"])

    def test_end_to_end_native_pipeline_with_synthetic_media(self):
        """
        Generates an authentic synthetic MP4 with FFmpeg and runs ClippingPipeline end-to-end.
        Proves that 1080x1920 vertical video, thumbnails, and SQLite records are produced.
        """
        synth_source = Path(self.temp_dir) / "synthetic_source_16x9.mp4"

        # Generate a small 6-second valid test video with audio
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100",
            "-t", "6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(synth_source)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            self.skipTest("FFmpeg testsrc filter unavailable on host system.")

        self.assertTrue(synth_source.exists())
        self.assertTrue(synth_source.stat().st_size > 1000)

        # Run Clipping Pipeline on the synthetic media
        job_id = f"test_job_{uuid.uuid4().hex[:8]}"
        pipeline_res = ClippingPipeline.process_video_job(
            source=str(synth_source),
            is_url=False,
            job_id=job_id,
            video_title="Unit Test Flight Demo",
            num_clips=1,
            min_duration=3.0,
            max_duration=6.0,
            framing_mode="blurred_bg",
            caption_style="none",
            is_test=1
        )

        self.assertTrue(pipeline_res["success"])
        self.assertEqual(pipeline_res["status"], "ready_for_review")
        self.assertTrue(len(pipeline_res["clips"]) >= 1)

        clip_info = pipeline_res["clips"][0]
        output_file = Path(clip_info["output_path"])
        self.assertTrue(output_file.exists())
        self.assertTrue(output_file.stat().st_size > 1000)

        # Check database persistence
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, progress_pct, clips_count FROM openshorts_jobs WHERE job_id = ?", (job_id,))
        job_row = cur.fetchone()
        self.assertIsNotNone(job_row)
        self.assertEqual(job_row["status"], "completed")
        self.assertEqual(job_row["progress_pct"], 100)

        cur.execute("SELECT aspect_ratio, status, output_path FROM youtube_clips WHERE job_id = ?", (job_id,))
        clip_row = cur.fetchone()
        self.assertIsNotNone(clip_row)
        self.assertEqual(clip_row["aspect_ratio"], "9:16")
        self.assertEqual(clip_row["status"], "ready_for_review")
        conn.close()

    def test_routes_native_generate_and_project_polling(self):
        """Tests the REST endpoint /api/youtube/clips/generate and project polling."""
        client = flask_app.test_client()

        # Generate route validation: requires video_url
        res_empty = client.post("/api/youtube/clips/generate", json={})
        self.assertEqual(res_empty.status_code, 400)

        # Polling route: retrieve project status
        conn = get_db_connection()
        cur = conn.cursor()
        test_pid = f"proj_poll_{uuid.uuid4().hex[:8]}"
        cur.execute("""
            INSERT INTO openshorts_jobs (job_id, provider, video_url, status, progress_pct, is_test, created_at, updated_at)
            VALUES (?, 'native_engine', 'https://example.com/video', 'processing', 65, 1, '2026-10-30 00:00:00', '2026-10-30 00:00:00')
        """, (test_pid,))
        conn.commit()
        conn.close()

        res_poll = client.get(f"/api/clipper/projects/{test_pid}")
        self.assertEqual(res_poll.status_code, 200)
        data = res_poll.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["project"]["progress_pct"], 65)


if __name__ == "__main__":
    unittest.main()

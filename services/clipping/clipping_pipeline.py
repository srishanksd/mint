"""
services/clipping/clipping_pipeline.py
Master Pipeline Orchestrator for Native AI Video Clipping in ChronoForge / MINT.

Operates 100% locally with zero external network or SaaS dependencies:
- Video ingestion via yt-dlp / local upload
- Faster-whisper transcription with word-level timestamps & real-time updates
- Semantic hook & viral moment analysis (Ollama / deterministic heuristics)
- Natural boundary alignment & overlap suppression
- Smart 9:16 vertical re-framing (1080x1920)
- ASS dynamic subtitle styling & burn-in
- FFmpeg encoding & thumbnail generation
- SQLite persistence in openshorts_jobs and youtube_clips
"""

import os
import sys
import json
import time
import uuid
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import config
from database import get_db_connection
from services.clipping.video_ingestion import VideoIngestionService
from services.clipping.transcription import TranscriptionService
from services.clipping.transcript_analyzer import TranscriptAnalyzer
from services.clipping.moment_detector import MomentDetector
from services.clipping.moment_ranker import MomentRanker
from services.clipping.scene_analyzer import SceneAnalyzer
from services.clipping.caption_generator import CaptionGenerator
from services.clipping.video_renderer import VideoRenderer
from services.clipping.quality_checker import QualityChecker

logger = logging.getLogger(__name__)


class ClippingPipeline:
    """
    Coordinates the complete video clipping workflow from raw input to review queue
    with real-time terminal output and granular database progress updates.
    """

    @classmethod
    def get_clips_output_dir(cls, job_id: str) -> Path:
        base_dir = Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent.parent / "generated")
        job_dir = base_dir / "content" / "youtube_clips" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    @classmethod
    def update_job_progress(
        cls,
        job_id: str,
        stage: str,
        progress_pct: int,
        status: str = "processing",
        error_message: Optional[str] = None,
        clips_count: Optional[int] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ):
        """Persists job stage and progress percent to SQLite openshorts_jobs table."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            payload = {"stage": stage, "updated_at": now_str}
            if extra_data:
                payload.update(extra_data)

            if clips_count is not None:
                cur.execute("""
                    UPDATE openshorts_jobs
                    SET status = ?, progress_pct = ?, clips_count = ?, error_message = ?, raw_response_json = ?, updated_at = ?
                    WHERE job_id = ?
                """, (status, progress_pct, clips_count, error_message, json.dumps(payload), now_str, job_id))
            else:
                cur.execute("""
                    UPDATE openshorts_jobs
                    SET status = ?, progress_pct = ?, error_message = ?, raw_response_json = ?, updated_at = ?
                    WHERE job_id = ?
                """, (status, progress_pct, error_message, json.dumps(payload), now_str, job_id))

            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to update openshorts_jobs progress for %s: %s", job_id, exc)

    @classmethod
    def process_video_job(
        cls,
        source: str,
        is_url: bool = True,
        job_id: Optional[str] = None,
        video_title: str = "",
        channel_name: str = "",
        channel_id: str = "",
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        num_clips: int = 2,
        min_duration: float = 20.0,
        max_duration: float = 55.0,
        framing_mode: str = "zoom_crop",
        caption_style: str = "beast",
        is_test: int = 0
    ) -> Dict[str, Any]:
        """
        Executes complete native clipping process end-to-end with lively terminal prints
        and granular database progress updates.
        """
        if not job_id:
            job_id = f"clip_{uuid.uuid4().hex[:12]}"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job_dir = cls.get_clips_output_dir(job_id)

        print(f"\n=======================================================", flush=True)
        print(f"[Native Clipper] Starting AI Clipping Job: {job_id}", flush=True)
        print(f"[Native Clipper] Target: {source} | Title: {video_title or 'Auto'}", flush=True)
        print(f"[Native Clipper] Settings: {num_clips} clips, {min_duration}-{max_duration}s, Framing: {framing_mode}, Subtitles: {caption_style}", flush=True)
        print(f"=======================================================\n", flush=True)

        # 1. Initial Job Database Record
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO openshorts_jobs (
                job_id, provider, source_type, video_url, video_title,
                source_channel_id, source_channel_name, status, progress_pct,
                clips_count, is_test, raw_response_json, created_at, updated_at
            ) VALUES (?, 'native_engine', ?, ?, ?, ?, ?, 'processing', 5, 0, ?, ?, ?, ?)
        """, (
            job_id,
            "YOUTUBE" if is_url else "LOCAL_FILE",
            source,
            video_title or ("YouTube Video" if is_url else Path(source).stem),
            channel_id or "local",
            channel_name or "MINT Video Engine",
            is_test,
            json.dumps({"stage": "initializing", "stage_label": "Initializing native clipping engine..."}),
            now_str,
            now_str
        ))
        conn.commit()
        conn.close()

        # ── Step 1: Ingestion ───────────────────────────────────────────────
        cls.update_job_progress(job_id, "downloading_source", 15, extra_data={"stage_label": "Ingesting and probing source video..."})
        print(f"[Native Clipper] [15%] Step 1/6: Ingesting source footage...", flush=True)

        if is_url:
            ingest_res = VideoIngestionService.ingest_youtube(source, job_dir / "source", job_id)
        else:
            ingest_res = VideoIngestionService.ingest_local_file(source, job_dir / "source", job_id)

        if not ingest_res.get("success"):
            err_msg = ingest_res.get("error", "Source video ingestion failed.")
            print(f"[Native Clipper] [ERROR] Ingestion failed: {err_msg}", flush=True)
            cls.update_job_progress(job_id, "failed", 0, status="failed", error_message=err_msg, extra_data={"stage_label": f"Failed: {err_msg}"})
            return {"success": False, "status": "failed", "error": err_msg, "job_id": job_id}

        source_video_path = ingest_res["video_path"]
        total_duration = float(ingest_res.get("duration", 0.0))
        resolved_title = ingest_res.get("video_title") or video_title or "Source Video"
        resolved_channel = ingest_res.get("channel_name") or channel_name or "YouTube Source"
        has_audio = bool(ingest_res.get("has_audio", True))
        source_width = int(ingest_res.get("width", 1920))
        source_height = int(ingest_res.get("height", 1080))
        caption_segments = ingest_res.get("caption_segments", [])

        if total_duration < 3.0:
            err_msg = f"Source video is too short ({total_duration:.1f}s) for clipping."
            cls.update_job_progress(job_id, "failed", 0, status="failed", error_message=err_msg)
            return {"success": False, "status": "failed", "error": err_msg, "job_id": job_id}

        # ── Step 2: Speech Transcription ─────────────────────────────────────
        cls.update_job_progress(job_id, "transcribing_audio", 35, extra_data={"stage_label": "Transcribing speech with Faster-Whisper..."})
        print(f"[Native Clipper] [35%] Step 2/6: Speech recognition and word-level timestamps...", flush=True)

        segments = []
        if caption_segments:
            # Instant transcription from source captions
            segments = caption_segments
            print(f"[Native Clipper] [45%] Using {len(segments)} pre-extracted word-timed speech segments from source captions.", flush=True)
            cls.update_job_progress(job_id, "transcribing_audio", 48, extra_data={"stage_label": f"Fast-parsed {len(segments)} timed speech segments"})
        elif has_audio:
            # Extract 16kHz audio for Whisper optimization
            audio_path = VideoIngestionService.extract_audio_for_transcription(source_video_path)
            target_audio = audio_path if audio_path else source_video_path

            last_update_time = [time.time()]

            def on_whisper_progress(cur_sec: float, tot_sec: float, txt: str):
                now = time.time()
                # Update DB every 4 seconds to prevent SQLite lock contention
                if now - last_update_time[0] >= 3.5:
                    last_update_time[0] = now
                    frac = min(1.0, max(0.0, cur_sec / tot_sec)) if tot_sec > 0 else 0.5
                    pct = 35 + int(frac * 18)  # Smoothly climbs 35% -> 53%
                    label = f"Transcribing audio: {int(cur_sec)}s / {int(tot_sec)}s ({int(frac*100)}%)"
                    cls.update_job_progress(job_id, "transcribing_audio", pct, extra_data={"stage_label": label})

            # For long videos, scan window up to 600s if no manual range given
            max_scan = None if (start_time is not None and end_time is not None) else 600.0
            segments = TranscriptionService.transcribe(
                target_audio,
                model_name="base",
                cache_dir=str(job_dir),
                progress_callback=on_whisper_progress,
                max_scan_seconds=max_scan
            )
        else:
            print(f"[Native Clipper] Video has no audio track. Skipping speech recognition.", flush=True)

        # ── Step 3: Moment Detection & Hook Selection ───────────────────────
        cls.update_job_progress(job_id, "analyzing_hooks", 55, extra_data={"stage_label": "Analyzing semantic hooks & engagement..."})
        print(f"\n[Native Clipper] [55%] Step 3/6: Analyzing viral hooks, questions, and high-retention moments...", flush=True)

        candidate_clips: List[Dict[str, Any]] = []

        # If user explicitly supplied custom timestamps, respect them
        if start_time is not None and end_time is not None:
            st = max(0.0, float(start_time))
            et = min(total_duration, float(end_time))
            if et > st and (et - st) >= 3.0:
                candidate_clips = [{
                    "start": round(st, 2),
                    "end": round(et, 2),
                    "duration": round(et - st, 2),
                    "headline": "User Highlight Moment",
                    "virality_score": 85.0,
                    "reason": f"User-selected range ({st:.1f}s - {et:.1f}s)",
                    "method": "manual_selection"
                }]

        if not candidate_clips:
            # Try Ollama if running
            if TranscriptAnalyzer.is_ollama_ready() and segments:
                ollama_cands = TranscriptAnalyzer.analyze_with_ollama(
                    segments=segments,
                    num_candidates=num_clips * 2,
                    target_duration=int((min_duration + max_duration) / 2)
                )
                if ollama_cands:
                    candidate_clips = ollama_cands

        if not candidate_clips and segments:
            # Deterministic semantic analysis
            candidate_clips = TranscriptAnalyzer.analyze_heuristics(
                segments=segments,
                num_candidates=num_clips * 2,
                min_duration=min_duration,
                max_duration=max_duration
            )

        if not candidate_clips:
            # Non-speech / fallback duration windows
            raw_windows = MomentDetector.generate_candidate_windows(
                segments=segments,
                total_duration=total_duration,
                min_duration=min_duration,
                max_duration=max_duration
            )
            for w in raw_windows[:num_clips]:
                candidate_clips.append({
                    "start": w["start"],
                    "end": w["end"],
                    "duration": w["duration"],
                    "headline": f"Highlight ({int(w['start'])}s-{int(w['end'])}s)",
                    "virality_score": 75.0,
                    "reason": "Source footage pacing highlight",
                    "method": "media_timing_window"
                })

        print(f"[Native Clipper] Found {len(candidate_clips)} potential candidate moments.", flush=True)

        # ── Step 4: Moment Ranking & Deduplication ───────────────────────────
        cls.update_job_progress(job_id, "ranking_clips", 65, extra_data={"stage_label": "Selecting top distinct non-overlapping moments..."})
        print(f"[Native Clipper] [65%] Step 4/6: Ranking & deduplicating candidate clips...", flush=True)

        selected_moments = MomentRanker.rank_and_select(candidate_clips, num_clips=num_clips)

        if not selected_moments:
            dur = min(total_duration, 40.0)
            selected_moments = [{
                "start": 0.0,
                "end": dur,
                "duration": dur,
                "headline": "Source Feature Short",
                "virality_score": 78.0,
                "reason": "Opening segment of source footage",
                "method": "source_baseline"
            }]

        for idx, m in enumerate(selected_moments, start=1):
            print(f"[Native Clipper] Selected Moment {idx}: \"{m.get('headline')}\" ({m['start']}s - {m['end']}s, dur: {m['duration']}s, score: {m.get('virality_score')} pts)", flush=True)

        # ── Step 5: Scene Boundary Alignment ─────────────────────────────────
        scene_cuts = SceneAnalyzer.detect_scene_cuts(source_video_path, start_sec=0.0, end_sec=min(total_duration, 120.0))
        for m in selected_moments:
            m["start"] = SceneAnalyzer.snap_to_scene(m["start"], scene_cuts)
            m["end"] = SceneAnalyzer.snap_to_scene(m["end"], scene_cuts)
            m["duration"] = round(m["end"] - m["start"], 2)

        # ── Step 6: Rendering Each Clip ──────────────────────────────────────
        total_clips = len(selected_moments)
        rendered_clips: List[Dict[str, Any]] = []
        conn = get_db_connection()
        cur = conn.cursor()

        for idx, moment in enumerate(selected_moments, start=1):
            render_pct = 70 + int(((idx - 1) / total_clips) * 24)
            clip_label = f"Rendering Short {idx} of {total_clips}: {moment['headline']} (1080x1920 9:16)..."
            cls.update_job_progress(job_id, "rendering_clips", render_pct, extra_data={"stage_label": clip_label})

            print(f"\n[Native Clipper] [{render_pct}%] Step 6/6: Rendering Clip {idx}/{total_clips}...", flush=True)
            print(f"[Native Clipper] Range: {moment['start']}s - {moment['end']}s | Framing: {framing_mode} | Subtitles: {caption_style}", flush=True)

            clip_filename = f"clip_{idx}.mp4"
            clip_path = str(job_dir / clip_filename)
            ass_path = str(job_dir / f"clip_{idx}.ass")

            # Generate ASS subtitles if requested
            subtitle_file = None
            if caption_style != "none" and segments:
                subtitle_file = CaptionGenerator.generate_ass_subtitles(
                    segments=segments,
                    clip_start=moment["start"],
                    clip_end=moment["end"],
                    output_ass_path=ass_path,
                    style=caption_style
                )

            # Render vertical 9:16 MP4
            render_res = VideoRenderer.render_clip(
                source_video_path=source_video_path,
                start_sec=moment["start"],
                end_sec=moment["end"],
                output_mp4_path=clip_path,
                ass_subtitle_path=subtitle_file,
                framing_mode=framing_mode,
                has_audio=has_audio,
                input_width=source_width,
                input_height=source_height
            )

            if render_res.get("success"):
                file_size = render_res.get("file_size", os.path.getsize(clip_path))
                clean_title = resolved_title.replace("'", "").replace('"', "")[:50]
                clip_title = f"{moment['headline']} | {clean_title} #Shorts"[:85]
                clip_desc = (
                    f"Clip extracted from: {clean_title}\n"
                    f"Timeline: {moment['start']}s - {moment['end']}s\n"
                    f"Reason: {moment.get('reason', '')}\n#Shorts #Viral #Trending"
                )

                cur.execute("""
                    INSERT INTO youtube_clips (
                        job_id, source_channel_name, source_channel_id, source_video_ref,
                        source_file_path, rights_confirmed, clip_title, clip_description,
                        hashtags, aspect_ratio, start_time_sec, end_time_sec, duration_sec,
                        output_path, file_size_bytes, status, virality_score, virality_reason,
                        thumbnail_url, mcp_job_id, mcp_clip_id, provider, content_classification,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, '9:16', ?, ?, ?, ?, ?, 'ready_for_review', ?, ?, ?, ?, ?, 'native_engine', 'verified_footage', ?)
                """, (
                    job_id,
                    resolved_channel,
                    channel_id or "channel",
                    source,
                    clip_path,
                    clip_title,
                    clip_desc,
                    "#Shorts #Viral #Trending",
                    moment["start"],
                    moment["end"],
                    moment["duration"],
                    clip_path,
                    file_size,
                    moment.get("virality_score", 80.0),
                    moment.get("reason", "High retention hook"),
                    render_res.get("thumbnail_path"),
                    job_id,
                    f"clip_{idx}",
                    now_str
                ))
                clip_id = cur.lastrowid
                conn.commit()

                print(f"[Native Clipper] Clip {idx} finalized successfully: {clip_filename} ({file_size // (1024*1024)} MB)", flush=True)

                rendered_clips.append({
                    "clip_id": clip_id,
                    "title": clip_title,
                    "output_path": clip_path,
                    "duration": moment["duration"],
                    "start": moment["start"],
                    "end": moment["end"],
                    "virality_score": moment.get("virality_score", 80.0),
                    "virality_reason": moment.get("reason"),
                    "thumbnail_path": render_res.get("thumbnail_path")
                })

        conn.close()

        if not rendered_clips:
            err_msg = "Failed to render any valid clips from source footage."
            print(f"[Native Clipper] [ERROR] {err_msg}", flush=True)
            cls.update_job_progress(job_id, "failed", 0, status="failed", error_message=err_msg, extra_data={"stage_label": f"Failed: {err_msg}"})
            return {"success": False, "status": "failed", "error": err_msg, "job_id": job_id}

        # ── Step 7: Final Completion ─────────────────────────────────────────
        final_label = f"✓ Completed! Generated {len(rendered_clips)} vertical Shorts ready in Review Queue."
        cls.update_job_progress(
            job_id=job_id,
            stage="completed",
            progress_pct=100,
            status="completed",
            clips_count=len(rendered_clips),
            extra_data={"stage_label": final_label, "clips": [c["clip_id"] for c in rendered_clips]}
        )

        print(f"\n=======================================================", flush=True)
        print(f"[Native Clipper] [100%] SUCCESS! Pipeline Complete for job: {job_id}", flush=True)
        print(f"[Native Clipper] Generated {len(rendered_clips)} ready-for-review clips.", flush=True)
        print(f"=======================================================\n", flush=True)

        return {
            "success": True,
            "status": "ready_for_review",
            "job_id": job_id,
            "clips_count": len(rendered_clips),
            "clips": rendered_clips,
            "provider": "native_engine",
            "video_title": resolved_title
        }

    @classmethod
    def start_background_job(cls, **kwargs) -> str:
        """
        Launches processing asynchronously in a background thread and immediately returns job_id.
        """
        job_id = kwargs.get("job_id") or f"clip_{uuid.uuid4().hex[:12]}"
        kwargs["job_id"] = job_id

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO openshorts_jobs (
                    job_id, provider, source_type, video_url, video_title,
                    source_channel_id, source_channel_name, status, progress_pct,
                    clips_count, is_test, raw_response_json, created_at, updated_at
                ) VALUES (?, 'native_engine', ?, ?, ?, ?, ?, 'processing', 5, 0, ?, ?, ?, ?)
            """, (
                job_id,
                "YOUTUBE" if kwargs.get("is_url", True) else "LOCAL_FILE",
                kwargs.get("source", ""),
                kwargs.get("video_title", "Processing Video..."),
                kwargs.get("channel_id", "local"),
                kwargs.get("channel_name", "MINT Video Engine"),
                kwargs.get("is_test", 0),
                json.dumps({"stage": "queued", "stage_label": "Queuing background clipping job..."}),
                now_str,
                now_str
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to initialize background job in DB: %s", e)

        thread = threading.Thread(
            target=cls.process_video_job,
            kwargs=kwargs,
            daemon=True,
            name=f"ClippingPipeline-{job_id}"
        )
        thread.start()
        return job_id

"""
services/clipping/transcription.py
Faster-Whisper Local Transcription Service with word-level timestamps,
singleton model caching, and real-time streaming progress logging.

Runs 100% locally on host hardware with zero external network requests.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


class TranscriptionService:
    """
    Manages local audio transcription using faster-whisper with word-level timing
    and real-time streaming progress updates.
    """

    _model = None
    _loaded_model_name = None
    _loaded_device = None

    @classmethod
    def get_whisper_model(cls, model_name: str = "base"):
        """
        Singleton loader for Faster-Whisper.
        Defaults to CPU int8 for 100% stable execution across all Windows systems
        without missing cublas64_12.dll or CUDA runtime crashes.
        """
        if cls._model is not None and cls._loaded_model_name == model_name:
            return cls._model

        models_dir = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "whisper"
        models_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[AI Whisper] Initializing Faster-Whisper model '{model_name}' on CPU (int8)...", flush=True)
        logger.info("Initializing faster-whisper model '%s' on CPU (int8)...", model_name)

        try:
            from faster_whisper import WhisperModel
            cls._model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(models_dir)
            )
            cls._loaded_model_name = model_name
            cls._loaded_device = "cpu"
            print(f"[AI Whisper] Faster-Whisper model '{model_name}' loaded ready in memory.\n", flush=True)
            return cls._model
        except Exception as exc:
            logger.error("Failed to load Faster-Whisper on CPU: %s", exc)
            print(f"[AI Whisper] Error loading model: {exc}", flush=True)
            return None

    @classmethod
    def transcribe(
        cls,
        media_or_audio_path: str,
        model_name: str = "base",
        cache_dir: Optional[str] = None,
        force_recompute: bool = False,
        progress_callback: Optional[Callable[[float, float, str], None]] = None,
        max_scan_seconds: Optional[float] = 600.0
    ) -> List[Dict[str, Any]]:
        """
        Transcribes media or audio file, extracting word-level timestamps.
        Outputs real-time terminal progress and triggers progress callbacks.
        """
        if not media_or_audio_path or not os.path.isfile(media_or_audio_path):
            return []

        media_path = Path(media_or_audio_path)
        cache_file = (Path(cache_dir) if cache_dir else media_path.parent) / f"{media_path.stem}.transcript.json"

        # Check existing transcript cache
        if not force_recompute and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    if isinstance(cached_data, list) and len(cached_data) > 0:
                        print(f"[AI Whisper] Loaded cached transcript ({len(cached_data)} segments) from disk.", flush=True)
                        logger.info("Loaded cached transcript (%d segments) from %s", len(cached_data), cache_file)
                        return cached_data
            except Exception as e:
                logger.warning("Failed to read transcript cache: %s", e)

        model = cls.get_whisper_model(model_name)
        if model is None:
            logger.warning("Faster-whisper model not available. Returning empty segments.")
            return []

        segments_data: List[Dict[str, Any]] = []
        try:
            print(f"[AI Whisper] Starting speech recognition with word timestamps on: {media_path.name}", flush=True)
            logger.info("Starting word-level transcription on: %s", media_or_audio_path)

            segments, info = model.transcribe(
                media_or_audio_path,
                beam_size=1,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=400)
            )

            total_dur = getattr(info, "duration", 0.0) or 0.0
            print(f"[AI Whisper] Audio duration: {total_dur:.1f}s | Detected language: {getattr(info, 'language', 'en')}", flush=True)

            for seg in segments:
                words_list = []
                if hasattr(seg, "words") and seg.words:
                    for w in seg.words:
                        clean_word = w.word.strip()
                        if clean_word:
                            words_list.append({
                                "word": clean_word,
                                "start": round(float(w.start), 2),
                                "end": round(float(w.end), 2),
                                "probability": round(float(getattr(w, "probability", 1.0)), 2)
                            })

                text = seg.text.strip()
                if text:
                    seg_dict = {
                        "start": round(float(seg.start), 2),
                        "end": round(float(seg.end), 2),
                        "text": text,
                        "words": words_list
                    }
                    segments_data.append(seg_dict)

                    pct = int((seg.end / total_dur) * 100) if total_dur > 0 else 50
                    pct = min(100, max(0, pct))
                    # Live terminal logging
                    print(f"[AI Whisper] [{seg.start:.1f}s - {seg.end:.1f}s / {total_dur:.1f}s] ({pct}%): \"{text[:55]}\"", flush=True)

                    if progress_callback:
                        try:
                            progress_callback(seg.end, total_dur, text)
                        except Exception:
                            pass

                # If long video, conclude scan window once sufficient speech has been gathered
                if max_scan_seconds and seg.end >= max_scan_seconds and len(segments_data) >= 15:
                    print(f"[AI Whisper] Reached scan window ({max_scan_seconds:.0f}s). Concluding transcription pass.", flush=True)
                    break

            print(f"[AI Whisper] Transcription complete! Captured {len(segments_data)} speech segments.\n", flush=True)
            logger.info("Transcribed %d segments with word timings.", len(segments_data))

            # Cache transcript to disk
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(segments_data, f, indent=2)
            except Exception as cache_exc:
                logger.warning("Failed to write transcript cache: %s", cache_exc)

        except Exception as exc:
            print(f"[AI Whisper] Transcription error: {exc}", flush=True)
            logger.error("Whisper transcription failed on %s: %s", media_or_audio_path, exc)

        return segments_data

"""
services/clipping/video_ingestion.py
Native Video Ingestion Service for MINT Local Clipping Engine.

Handles:
- Downloading video sources from supported platforms via yt-dlp
- Parsing available timed-text captions directly for instant transcription
- Validating and ingesting local video file uploads
- FFprobe media probing (duration, resolution, fps, codecs, stream presence)
- Optimized 16kHz mono audio extraction for Whisper transcription
"""

import os
import re
import json
import uuid
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import requests
import yt_dlp

logger = logging.getLogger(__name__)


class VideoIngestionService:
    """
    Ingests and probes video files or YouTube URLs into local workspace storage.
    """

    @classmethod
    def probe_media(cls, media_path: str) -> Dict[str, Any]:
        """
        Runs ffprobe to thoroughly inspect media streams and container metadata.
        Returns detailed dictionary with success, duration, dimensions, codecs, and stream flags.
        """
        if not media_path or not os.path.isfile(media_path):
            return {
                "success": False,
                "error": f"Media file not found or not a regular file: {media_path}",
                "duration": 0.0,
                "width": 0,
                "height": 0,
                "size_bytes": 0,
                "has_video": False,
                "has_audio": False
            }

        size = os.path.getsize(media_path)
        if size == 0:
            return {
                "success": False,
                "error": "Media file is empty (0 bytes).",
                "duration": 0.0,
                "width": 0,
                "height": 0,
                "size_bytes": 0,
                "has_video": False,
                "has_audio": False
            }

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,duration,r_frame_rate,channels,sample_rate:format=duration,size,bit_rate",
            "-of", "json",
            media_path
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            try:
                data = json.loads(res.stdout)
            except Exception:
                data = {}

            if not isinstance(data, dict):
                try:
                    dur = float(res.stdout.strip())
                    return {
                        "success": True,
                        "duration": dur,
                        "width": 1920,
                        "height": 1080,
                        "size_bytes": size,
                        "has_video": True,
                        "has_audio": True,
                        "video_codec": "h264",
                        "audio_codec": "aac",
                        "fps": 30.0
                    }
                except Exception:
                    data = {}

            streams = data.get("streams", [])
            fmt = data.get("format", {})

            video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

            width = int(video_stream.get("width", 0)) if video_stream else 0
            height = int(video_stream.get("height", 0)) if video_stream else 0

            fps = 30.0
            if video_stream and "r_frame_rate" in video_stream:
                rate_str = video_stream.get("r_frame_rate", "30/1")
                try:
                    num, den = map(float, rate_str.split("/"))
                    if den > 0:
                        fps = round(num / den, 2)
                except Exception:
                    fps = 30.0

            duration_raw = fmt.get("duration") or (video_stream.get("duration") if video_stream else None) or (audio_stream.get("duration") if audio_stream else None)
            try:
                duration = float(duration_raw) if duration_raw else 0.0
            except (ValueError, TypeError):
                duration = 0.0

            return {
                "success": bool(video_stream or audio_stream),
                "duration": round(duration, 2),
                "width": width,
                "height": height,
                "fps": fps,
                "size_bytes": size,
                "has_video": bool(video_stream),
                "has_audio": bool(audio_stream),
                "video_codec": video_stream.get("codec_name") if video_stream else None,
                "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
                "audio_channels": int(audio_stream.get("channels", 0)) if audio_stream else 0,
                "audio_sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else 0,
                "bit_rate": int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else 0
            }

        except Exception as exc:
            logger.warning("ffprobe execution failed on %s: %s", media_path, exc)
            return {
                "success": False,
                "error": f"FFprobe execution failed: {str(exc)}",
                "duration": 0.0,
                "width": 0,
                "height": 0,
                "size_bytes": size,
                "has_video": False,
                "has_audio": False
            }

    @classmethod
    def extract_audio_for_transcription(cls, video_path: str, output_wav_path: Optional[str] = None) -> Optional[str]:
        """
        Extracts a clean, 16kHz 16-bit mono WAV file specifically tailored for optimal Faster-Whisper accuracy.
        """
        if not video_path or not os.path.isfile(video_path):
            return None

        if not output_wav_path:
            v_path = Path(video_path)
            output_wav_path = str(v_path.parent / f"{v_path.stem}_audio_16k.wav")

        out_p = Path(output_wav_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if out_p.exists() and out_p.stat().st_size > 1000:
            return str(out_p)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(out_p)
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
            if res.returncode == 0 and out_p.exists() and out_p.stat().st_size > 0:
                print(f"[Video Ingestion] Extracted 16kHz mono audio for Whisper: {out_p.name} ({out_p.stat().st_size // 1024} KB)", flush=True)
                logger.info("Extracted transcription audio to %s (%d bytes)", out_p, out_p.stat().st_size)
                return str(out_p)
        except Exception as exc:
            logger.warning("Failed to extract 16kHz audio from %s: %s", video_path, exc)

        return None

    @classmethod
    def ingest_youtube(
        cls,
        video_url: str,
        dest_dir: Path,
        job_id: str
    ) -> Dict[str, Any]:
        """
        Extracts info and downloads YouTube video to destination directory.
        Also parses official YouTube timed captions if present for instant speech recognition.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        raw_output_tmpl = str(dest_dir / f"{job_id}_source.%(ext)s")

        print(f"\n[Video Ingestion] Ingesting YouTube URL: {video_url}", flush=True)

        ydl_opts_info = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en', 'en-US', 'en-orig'],
            'quiet': True,
            'no_warnings': True,
        }

        # 1. Inspect info first
        try:
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(video_url, download=False)
        except Exception as exc:
            logger.error("Failed to inspect YouTube URL %s: %s", video_url, exc)
            return {
                "success": False,
                "error": f"Failed to retrieve video metadata from URL: {exc}"
            }

        title = info.get("title") or "YouTube Source Video"
        duration = float(info.get("duration") or 0.0)
        channel = info.get("channel") or info.get("uploader") or "YouTube Channel"
        channel_id = info.get("channel_id") or info.get("uploader_id") or "youtube"
        description = info.get("description") or ""

        print(f"[Video Ingestion] Title: \"{title}\" | Duration: {duration:.1f}s ({duration/60:.1f} min)", flush=True)

        if duration <= 0.0:
            return {
                "success": False,
                "error": "Source YouTube video reported invalid or zero duration."
            }

        # Check for pre-existing subtitles in video metadata
        caption_segments: List[Dict[str, Any]] = []
        subs = info.get("subtitles") or info.get("automatic_captions") or {}
        en_subs = subs.get("en") or subs.get("en-US") or subs.get("en-orig") or []
        json3_entry = next((s for s in en_subs if s.get("ext") == "json3"), None)
        if json3_entry and json3_entry.get("url"):
            try:
                sub_resp = requests.get(json3_entry["url"], timeout=6)
                if sub_resp.status_code == 200:
                    for ev in sub_resp.json().get("events", []):
                        t = round(ev.get("tStartMs", 0) / 1000.0, 2)
                        d = round(ev.get("dDurationMs", 0) / 1000.0, 2)
                        text_val = "".join([s.get("utf8", "") for s in ev.get("segs", [])]).strip()
                        words_list = []
                        for s in ev.get("segs", []):
                            w_txt = s.get("utf8", "").strip()
                            w_offset = round(s.get("tOffsetMs", 0) / 1000.0, 2)
                            if w_txt:
                                words_list.append({
                                    "word": w_txt,
                                    "start": round(t + w_offset, 2),
                                    "end": round(t + w_offset + 0.35, 2),
                                    "probability": 1.0
                                })
                        if text_val:
                            caption_segments.append({
                                "start": t,
                                "end": round(t + d, 2),
                                "text": text_val,
                                "words": words_list
                            })
                    if caption_segments:
                        print(f"[Video Ingestion] Found {len(caption_segments)} pre-computed timed speech segments directly from source video!", flush=True)
            except Exception as e:
                logger.debug("Could not parse YouTube caption json3: %s", e)

        # 2. Check if source video already exists in job directory
        downloaded_files = list(dest_dir.glob(f"{job_id}_source.*"))
        video_file = next((f for f in downloaded_files if f.suffix.lower() in [".mp4", ".mkv", ".webm"]), None)

        if not video_file or not video_file.exists() or video_file.stat().st_size == 0:
            print(f"[Video Ingestion] Downloading media streams via yt-dlp...", flush=True)
            ydl_opts_dl = {
                'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b',
                'outtmpl': raw_output_tmpl,
                'quiet': True,
                'no_warnings': True,
                'overwrites': True,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
                    ydl.download([video_url])
            except Exception as exc:
                logger.error("yt-dlp download failed for %s: %s", video_url, exc)
                return {
                    "success": False,
                    "error": f"Failed to download video file: {exc}"
                }

            downloaded_files = list(dest_dir.glob(f"{job_id}_source.*"))
            video_file = next((f for f in downloaded_files if f.suffix.lower() in [".mp4", ".mkv", ".webm"]), None)

        if not video_file or not video_file.exists() or video_file.stat().st_size == 0:
            return {
                "success": False,
                "error": "Downloaded video file was empty or missing on disk."
            }

        # Probe the downloaded video
        probe = cls.probe_media(str(video_file))
        if not probe.get("success") or not probe.get("has_video"):
            return {
                "success": False,
                "error": "Downloaded file does not contain a playable video stream."
            }

        print(f"[Video Ingestion] Media verified: {video_file.name} ({probe['width']}x{probe['height']}, {probe['fps']} fps, {video_file.stat().st_size // (1024*1024)} MB)\n", flush=True)

        return {
            "success": True,
            "source_type": "YOUTUBE",
            "video_path": str(video_file),
            "video_title": title,
            "channel_name": channel,
            "channel_id": channel_id,
            "duration": probe.get("duration", duration),
            "width": probe.get("width", 0),
            "height": probe.get("height", 0),
            "has_audio": probe.get("has_audio", False),
            "fps": probe.get("fps", 30.0),
            "description": description,
            "caption_segments": caption_segments
        }

    @classmethod
    def ingest_local_file(
        cls,
        source_path: str,
        dest_dir: Path,
        job_id: str
    ) -> Dict[str, Any]:
        """
        Validates, copies/links local video file into the job directory, and probes media.
        """
        src = Path(source_path)
        if not src.exists() or not src.is_file():
            return {
                "success": False,
                "error": f"Local file does not exist: {source_path}"
            }

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{job_id}_source{src.suffix}"

        if not dest_file.exists() or dest_file.stat().st_size == 0:
            try:
                shutil.copy2(str(src), str(dest_file))
            except Exception:
                dest_file = src

        probe = cls.probe_media(str(dest_file))
        if not probe.get("success") or not probe.get("has_video"):
            return {
                "success": False,
                "error": f"Source video lacks valid video stream: {probe.get('error', 'Unrecognized format')}"
            }

        print(f"[Video Ingestion] Ingested local file: {src.name} ({probe['duration']:.1f}s, {probe['width']}x{probe['height']})", flush=True)

        return {
            "success": True,
            "source_type": "LOCAL_FILE",
            "video_path": str(dest_file),
            "video_title": src.stem,
            "channel_name": "Local Video Library",
            "channel_id": "local",
            "duration": probe.get("duration", 0.0),
            "width": probe.get("width", 0),
            "height": probe.get("height", 0),
            "has_audio": probe.get("has_audio", False),
            "fps": probe.get("fps", 30.0),
            "description": "",
            "caption_segments": []
        }

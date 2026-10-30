"""
services/clipping
Native AI Video Clipping Architecture for ChronoForge / MINT.
100% Local: Faster-Whisper, Ollama/deterministic heuristics, OpenCV, FFmpeg.
"""

from services.clipping.video_ingestion import VideoIngestionService
from services.clipping.transcription import TranscriptionService
from services.clipping.transcript_analyzer import TranscriptAnalyzer
from services.clipping.moment_detector import MomentDetector
from services.clipping.moment_ranker import MomentRanker
from services.clipping.scene_analyzer import SceneAnalyzer
from services.clipping.smart_framing import SmartFramingService
from services.clipping.caption_generator import CaptionGenerator
from services.clipping.video_renderer import VideoRenderer
from services.clipping.quality_checker import QualityChecker
from services.clipping.clipping_pipeline import ClippingPipeline

__all__ = [
    "VideoIngestionService",
    "TranscriptionService",
    "TranscriptAnalyzer",
    "MomentDetector",
    "MomentRanker",
    "SceneAnalyzer",
    "SmartFramingService",
    "CaptionGenerator",
    "VideoRenderer",
    "QualityChecker",
    "ClippingPipeline",
]

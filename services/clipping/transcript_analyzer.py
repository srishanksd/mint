"""
services/clipping/transcript_analyzer.py
Local AI Transcript Analyzer for Viral Hook & Content Extraction.

Combines local Ollama LLM inference (when available) with high-precision deterministic
semantic heuristics. Zero external APIs, zero paid cloud services.
"""

import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

# Core engagement & retention keywords for short-form video hooks
HOOK_PATTERNS = [
    r"\bhow to\b", r"\bthe secret\b", r"\bwhy you\b", r"\bstop doing\b",
    r"\bnever\b", r"\balways\b", r"\bthe biggest mistake\b", r"\bthis is why\b",
    r"\bhere is how\b", r"\bwhat if\b", r"\bnumber one rule\b", r"\bthe truth about\b",
    r"\bstep by step\b", r"\bif you want to\b", r"\bdo not make this\b"
]

HIGH_VALUE_TOPICS = [
    "revenue", "profit", "money", "growth", "strategy", "algorithm",
    "business", "million", "dollar", "scale", "system", "hack", "tool",
    "secret", "framework", "mistake", "fix", "blueprint", "automate", "ai"
]


class TranscriptAnalyzer:
    """
    Analyzes transcripts to identify viral hooks, key takeaways, and standalone topics.
    """

    @classmethod
    def is_ollama_ready(cls) -> bool:
        endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        try:
            r = requests.get(f"{endpoint}/api/tags", timeout=1.0)
            return r.status_code == 200
        except Exception:
            return False

    @classmethod
    def analyze_with_ollama(
        cls,
        segments: List[Dict[str, Any]],
        num_candidates: int = 3,
        target_duration: int = 40
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Queries local Ollama instance to find top viral moments.
        """
        endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.2")

        if not segments:
            return None

        # Sample transcript snippet up to 40 segments to fit prompt context
        snippet_lines = []
        for s in segments[:45]:
            snippet_lines.append(f"[{s['start']:.1f}s - {s['end']:.1f}s]: {s['text']}")
        transcript_text = "\n".join(snippet_lines)

        prompt = (
            f"Analyze this video transcript and identify the top {num_candidates} most engaging, high-retention "
            f"segments for YouTube Shorts / TikTok (each between 20 and 55 seconds in duration).\n\n"
            f"Transcript:\n{transcript_text}\n\n"
            f"Respond ONLY with a valid JSON array of objects with these exact keys:\n"
            f'[{{"start": <float>, "end": <float>, "headline": "<punchy 4-6 word hook>", '
            f'"virality_score": <int 72-90>, "reason": "<brief 1-sentence reason>"}}]'
        )

        try:
            r = requests.post(
                f"{endpoint}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": 400}
                },
                timeout=6.0
            )
            if r.status_code == 200:
                resp_text = r.json().get("response", "")
                json_start = resp_text.find("[")
                json_end = resp_text.rfind("]") + 1
                if json_start >= 0 and json_end > json_start:
                    parsed = json.loads(resp_text[json_start:json_end])
                    if isinstance(parsed, list) and len(parsed) > 0:
                        results = []
                        for item in parsed:
                            st = float(item.get("start", 0.0))
                            et = float(item.get("end", st + target_duration))
                            dur = round(et - st, 2)
                            if 15.0 <= dur <= 65.0:
                                score = float(min(91.0, max(70.0, float(item.get("virality_score", 80)))))
                                results.append({
                                    "start": round(st, 2),
                                    "end": round(et, 2),
                                    "duration": dur,
                                    "headline": item.get("headline", "High Retention Moment")[:60],
                                    "virality_score": score,
                                    "reason": f"Ollama AI: {item.get('reason', 'Strong hook and retention potential')}",
                                    "method": "ollama_analysis"
                                })
                        if results:
                            return results
        except Exception as exc:
            logger.debug("Ollama transcript analysis unavailable or timed out: %s", exc)

        return None

    @classmethod
    def analyze_heuristics(
        cls,
        segments: List[Dict[str, Any]],
        num_candidates: int = 3,
        min_duration: float = 20.0,
        max_duration: float = 55.0,
        target_duration: float = 38.0
    ) -> List[Dict[str, Any]]:
        """
        High-precision deterministic analysis scanning for hook sentences, keyword density,
        pacing, and closure markers.
        """
        if not segments:
            return []

        candidates = []
        total_segs = len(segments)

        for i, start_seg in enumerate(segments):
            start_time = start_seg["start"]
            hook_text = start_seg["text"].lower()

            # Calculate hook bonus
            hook_score = 0.0
            matched_hook = ""
            for pattern in HOOK_PATTERNS:
                if re.search(pattern, hook_text):
                    hook_score += 12.0
                    matched_hook = pattern.strip(r"\b")
                    break

            if "?" in start_seg["text"]:
                hook_score += 6.0
            if "!" in start_seg["text"]:
                hook_score += 4.0

            # Find matching end segment within target duration window
            accumulated_text = [start_seg["text"]]
            best_end_seg = None
            best_window_score = -1.0

            for j in range(i + 1, min(i + 25, total_segs)):
                curr_seg = segments[j]
                current_dur = curr_seg["end"] - start_time

                if current_dur < min_duration:
                    accumulated_text.append(curr_seg["text"])
                    continue
                if current_dur > max_duration:
                    break

                accumulated_text.append(curr_seg["text"])
                blob = " ".join(accumulated_text).lower()

                # Evaluate density of high-value topics
                topic_matches = [kw for kw in HIGH_VALUE_TOPICS if kw in blob]
                density_score = min(15.0, len(topic_matches) * 2.5)

                # Duration optimality penalty (prefer ~30-45s)
                dur_diff = abs(current_dur - target_duration)
                duration_penalty = min(8.0, dur_diff * 0.4)

                # Sentence closure bonus at end segment
                closure_bonus = 5.0 if curr_seg["text"].rstrip().endswith((".", "!", "?")) else 0.0

                composite_score = 70.0 + hook_score + density_score + closure_bonus - duration_penalty
                composite_score = min(91.0, max(70.0, composite_score))

                if composite_score > best_window_score:
                    best_window_score = composite_score
                    best_end_seg = curr_seg
                    best_topics = topic_matches

            if best_end_seg:
                end_time = best_end_seg["end"]
                dur = round(end_time - start_time, 2)

                # Build headline
                headline_words = [w.capitalize() for w in start_seg["text"].split()[:5]]
                clean_hook = " ".join(headline_words).rstrip(".,!?")
                if matched_hook:
                    headline = f"{matched_hook.title()} You Need to Know"
                elif best_topics:
                    headline = f"The Secret to {best_topics[0].title()}"
                elif clean_hook:
                    headline = f"{clean_hook}..."
                else:
                    headline = "Crucial Insight Breakdown"

                reason_desc = (
                    f"Strong opening hook ('{start_seg['text'][:35]}...') with "
                    f"{len(best_topics)} high-retention keywords and natural sentence conclusion."
                )

                candidates.append({
                    "start": round(start_time, 2),
                    "end": round(end_time, 2),
                    "duration": dur,
                    "headline": headline[:60],
                    "virality_score": round(best_window_score, 1),
                    "reason": reason_desc,
                    "method": "heuristic_semantic_analysis",
                    "topics": best_topics
                })

        # Sort candidates descending by score
        candidates.sort(key=lambda c: c["virality_score"], reverse=True)
        return candidates

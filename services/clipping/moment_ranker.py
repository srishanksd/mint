"""
services/clipping/moment_ranker.py
Moment Ranker and Deduplicator for Native Video Clipping.

Ranks candidates using multi-dimensional engagement metrics and applies temporal
overlap suppression (Non-Maximum Suppression) so returned clips are genuinely distinct.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class MomentRanker:
    """
    Ranks candidate moments and prunes overlapping windows.
    """

    @classmethod
    def calculate_overlap_ratio(cls, cand1: Dict[str, Any], cand2: Dict[str, Any]) -> float:
        """
        Calculates temporal Intersection over Union (IoU) between two time ranges.
        """
        s1, e1 = cand1["start"], cand1["end"]
        s2, e2 = cand2["start"], cand2["end"]

        overlap_start = max(s1, s2)
        overlap_end = min(e1, e2)
        overlap_dur = max(0.0, overlap_end - overlap_start)

        if overlap_dur <= 0.0:
            return 0.0

        min_dur = min(e1 - s1, e2 - s2)
        if min_dur <= 0.0:
            return 0.0

        # Overlap relative to the shorter clip
        return overlap_dur / min_dur

    @classmethod
    def deduplicate_candidates(
        cls,
        candidates: List[Dict[str, Any]],
        max_overlap_ratio: float = 0.35,
        max_clips: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Temporal Non-Maximum Suppression (NMS):
        Selects top-scoring candidates while rejecting any candidate that overlaps
        substantially with an already chosen higher-scoring candidate.
        """
        if not candidates:
            return []

        # Ensure candidates are sorted descending by virality_score
        sorted_cands = sorted(candidates, key=lambda c: c.get("virality_score", 0), reverse=True)
        selected: List[Dict[str, Any]] = []

        for cand in sorted_cands:
            has_heavy_overlap = False
            for sel in selected:
                overlap = cls.calculate_overlap_ratio(cand, sel)
                if overlap > max_overlap_ratio:
                    has_heavy_overlap = True
                    break

            if not has_heavy_overlap:
                selected.append(cand)
                if len(selected) >= max_clips:
                    break

        return selected

    @classmethod
    def rank_and_select(
        cls,
        candidates: List[Dict[str, Any]],
        num_clips: int = 3,
        max_overlap_ratio: float = 0.35
    ) -> List[Dict[str, Any]]:
        """
        Ranks candidates and returns the top distinct non-overlapping clips.
        """
        if not candidates:
            return []

        deduped = cls.deduplicate_candidates(candidates, max_overlap_ratio=max_overlap_ratio, max_clips=num_clips)
        logger.info("Selected %d top distinct clips from %d raw candidates.", len(deduped), len(candidates))
        return deduped

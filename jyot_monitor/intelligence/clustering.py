"""Story clustering and representative item selection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from jyot_monitor.intelligence.deduplication import MultimodalDeduplicator
from jyot_monitor.schemas import ItemSchema, StoryCluster


class StoryClusterer:
    """Groups duplicate and related items into story clusters."""

    def __init__(self, deduplicator: Optional[MultimodalDeduplicator] = None):
        self.deduplicator = deduplicator or MultimodalDeduplicator()

    def score_representative_quality(
        self,
        item: ItemSchema,
        ocr_text: Optional[str] = None,
        ocr_confidence: Optional[float] = None,
    ) -> float:
        """Scores candidate item quality to select the best story representative."""
        score = 0.0

        # Source credibility weight (0 to 30 pts)
        src = item.source.lower()
        if any(o in src for o in ["fda", "cpsc", "usda", "gov"]):
            score += 30.0
        elif "civic" in src or "news" in src:
            score += 20.0
        else:
            score += 10.0

        # Content length / evidence completeness (0 to 40 pts)
        combined_text = (item.text or "") + " " + (ocr_text or "")
        text_len = len(combined_text.strip())
        score += min(40.0, text_len / 10.0)

        # OCR confidence (0 to 20 pts)
        if ocr_confidence:
            score += (ocr_confidence / 100.0) * 20.0

        # Penalize items with safety/spam flags (-20 pts)
        if item.trust_and_safety_flags:
            score -= 20.0

        return score

    def cluster_items(
        self,
        items: List[ItemSchema],
        ocr_texts: Optional[Dict[str, str]] = None,
        ocr_confidences: Optional[Dict[str, float]] = None,
        phashes: Optional[Dict[str, str]] = None,
        existing_clusters: Optional[List[StoryCluster]] = None,
    ) -> List[StoryCluster]:
        """Clusters a list of items into stories, merging with existing clusters if applicable."""
        ocr_texts = ocr_texts or {}
        ocr_confidences = ocr_confidences or {}
        phashes = phashes or {}

        clusters: List[StoryCluster] = list(existing_clusters) if existing_clusters else []
        now = datetime.now(timezone.utc).isoformat()

        # Build mapping of item_id -> ItemSchema
        item_map = {it.item_id: it for it in items}

        for item in items:
            matched_cluster: Optional[StoryCluster] = None

            # Compare against existing cluster representatives
            for cluster in clusters:
                rep_item = item_map.get(cluster.representative_item_id)
                rep_text = rep_item.text if rep_item else ""
                rep_ocr = ocr_texts.get(cluster.representative_item_id)
                rep_phash = phashes.get(cluster.representative_item_id)

                is_dup, _, _ = self.deduplicator.check_duplicate(
                    text_a=item.text,
                    text_b=rep_text,
                    ocr_text_a=ocr_texts.get(item.item_id),
                    ocr_text_b=rep_ocr,
                    phash_a=phashes.get(item.item_id),
                    phash_b=rep_phash,
                )

                if is_dup:
                    matched_cluster = cluster
                    break

            if matched_cluster:
                if item.item_id not in matched_cluster.member_item_ids:
                    matched_cluster.member_item_ids.append(item.item_id)
                    matched_cluster.updated_at = now

                    # Check if new item should replace representative
                    current_rep = item_map.get(matched_cluster.representative_item_id)
                    current_rep_score = (
                        self.score_representative_quality(
                            current_rep,
                            ocr_texts.get(current_rep.item_id),
                            ocr_confidences.get(current_rep.item_id),
                        )
                        if current_rep
                        else -100.0
                    )
                    new_item_score = self.score_representative_quality(
                        item,
                        ocr_texts.get(item.item_id),
                        ocr_confidences.get(item.item_id),
                    )

                    if new_item_score > current_rep_score:
                        matched_cluster.representative_item_id = item.item_id
            else:
                # Create a new story cluster
                new_cluster = StoryCluster(
                    cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
                    topic="Safety Story",
                    representative_item_id=item.item_id,
                    member_item_ids=[item.item_id],
                    created_at=now,
                    updated_at=now,
                    max_urgency=0.0,
                    status="active",
                )
                clusters.append(new_cluster)

        return clusters

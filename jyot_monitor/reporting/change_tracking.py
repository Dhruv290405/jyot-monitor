"""Change tracking between successive digest runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from jyot_monitor.schemas import StoryCluster


class ChangeTracker:
    """Detects new stories, escalations, and evidence changes since previous run."""

    def compare(
        self,
        current_clusters: List[StoryCluster],
        previous_cluster_snapshots: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Compares current clusters with previous run snapshots.

        Returns {
            'new_stories': [...],
            'escalations': [...],
            'new_evidence': [...],
            'unchanged': [...]
        }
        """
        changes: Dict[str, List[Dict[str, Any]]] = {
            "new_stories": [],
            "escalations": [],
            "new_evidence": [],
            "unchanged": [],
        }

        if not previous_cluster_snapshots:
            for c in current_clusters:
                changes["new_stories"].append({
                    "cluster_id": c.cluster_id,
                    "topic": c.topic,
                    "urgency": c.max_urgency,
                    "items_count": len(c.member_item_ids),
                })
            return changes

        prev_map: Dict[str, Dict[str, Any]] = {
            p["cluster_id"]: p for p in previous_cluster_snapshots
        }

        for c in current_clusters:
            prev = prev_map.get(c.cluster_id)
            if not prev:
                changes["new_stories"].append({
                    "cluster_id": c.cluster_id,
                    "topic": c.topic,
                    "urgency": c.max_urgency,
                    "items_count": len(c.member_item_ids),
                })
            else:
                prev_urgency = float(prev.get("max_urgency", 0.0))
                prev_members_count = int(prev.get("items_count", 1))

                is_escalated = (c.max_urgency - prev_urgency) >= 10.0
                has_new_evidence = len(c.member_item_ids) > prev_members_count

                if is_escalated:
                    changes["escalations"].append({
                        "cluster_id": c.cluster_id,
                        "topic": c.topic,
                        "old_urgency": prev_urgency,
                        "new_urgency": c.max_urgency,
                    })
                elif has_new_evidence:
                    changes["new_evidence"].append({
                        "cluster_id": c.cluster_id,
                        "topic": c.topic,
                        "new_member_count": len(c.member_item_ids),
                    })
                else:
                    changes["unchanged"].append({
                        "cluster_id": c.cluster_id,
                        "topic": c.topic,
                        "urgency": c.max_urgency,
                    })

        return changes

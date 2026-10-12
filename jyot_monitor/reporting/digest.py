"""Polished Markdown digest generation for prioritised story clusters."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jyot_monitor.database import Database
from jyot_monitor.reporting.change_tracking import ChangeTracker
from jyot_monitor.safety.pii import PIIRedactor
from jyot_monitor.schemas import ProposalSchema, StoryCluster


class DigestGenerator:
    """Generates structured, executive-ready Markdown digests."""

    def __init__(
        self,
        db: Database,
        change_tracker: Optional[ChangeTracker] = None,
        redactor: Optional[PIIRedactor] = None,
    ):
        self.db = db
        self.change_tracker = change_tracker or ChangeTracker()
        self.redactor = redactor or PIIRedactor()

    def generate_digest(
        self,
        run_id: str,
        clusters: List[StoryCluster],
        top_n: int = 10,
        run_mode: str = "replay",
        previous_snapshots: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Generates a complete Markdown digest."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Rank clusters by max_urgency descending
        ranked_clusters = sorted(clusters, key=lambda c: c.max_urgency, reverse=True)[:top_n]

        # Calculate changes
        changes = self.change_tracker.compare(ranked_clusters, previous_snapshots)

        # Count pending proposals
        all_proposals = self.db.list_proposals()
        proposal_by_cluster = {p.cluster_id: p for p in all_proposals}
        pending_count = sum(1 for p in all_proposals if p.status.value == "pending")

        lines: List[str] = []
        lines.append("# 🚨 Jyot Public Safety & Recall Intelligence Digest")
        lines.append(f"**Run ID:** `{run_id}` | **Mode:** `{run_mode}` | **Generated:** {now_iso}")
        lines.append(
            f"**Total Stories Monitored:** {len(clusters)} | **Top Stories Displayed:** {len(ranked_clusters)} | "
            f"**Alert Proposals Pending Human Review:** {pending_count}\n"
        )
        lines.append("---")

        # 1. Executive Summary & Top Stories
        lines.append("## 📌 Prioritized Story Clusters\n")

        if not ranked_clusters:
            lines.append("_No active safety incidents or notices recorded in this run._\n")

        for idx, cluster in enumerate(ranked_clusters, 1):
            rep_item = self.db.get_item(cluster.representative_item_id)
            proposal = proposal_by_cluster.get(cluster.cluster_id)

            title = cluster.topic if cluster.topic != "Safety Story" else (
                (rep_item.text[:65] + "...") if rep_item and rep_item.text else f"Incident {cluster.cluster_id}"
            )
            title = title.replace("\n", " ").strip()

            urgency_badge = "🔴 CRITICAL" if cluster.max_urgency >= 75 else ("🟡 MODERATE" if cluster.max_urgency >= 50 else "🟢 LOW")
            lines.append(f"### {idx}. {title}")
            lines.append(f"- **Cluster ID:** `{cluster.cluster_id}` | **Urgency:** **{cluster.max_urgency}/100** ({urgency_badge})")
            lines.append(f"- **Duplicates Merged:** {len(cluster.member_item_ids) - 1} cross-modal / repost items")

            if rep_item:
                lines.append(f"- **Primary Source:** [{rep_item.source}]({rep_item.source_url})")
                lines.append(f"- **Published:** {rep_item.published_at}")

                # Redact evidence snippet
                clean_snippet, _ = self.redactor.redact(rep_item.text[:240])
                lines.append(f"- **Evidence Summary:** > *\"{clean_snippet}\"*")

                if rep_item.trust_and_safety_flags:
                    flags_str = ", ".join(f"`{f}`" for f in rep_item.trust_and_safety_flags)
                    lines.append(f"- **Trust & Safety Flags:** {flags_str}")

            if proposal:
                status_emoji = "⏳" if proposal.status.value == "pending" else ("✅" if proposal.status.value == "approved" else "❌")
                lines.append(
                    f"- **Human Alert Proposal:** {status_emoji} `{proposal.proposal_id}` "
                    f"(Status: **{proposal.status.value.upper()}**)"
                )
                lines.append(f"  - *Threshold Rationale:* {proposal.threshold_rationale}")
                if proposal.status.value == "pending":
                    lines.append(f"  - *Approve Command:* `python -m jyot_monitor approve {proposal.proposal_id}`")

            lines.append("")

        lines.append("---")

        # 2. What Changed Since Last Digest?
        lines.append("## 🔄 What Changed Since Last Digest?\n")

        if changes["new_stories"]:
            lines.append(f"### 🆕 New Stories ({len(changes['new_stories'])})")
            for ns in changes["new_stories"][:5]:
                lines.append(f"- Story `{ns['cluster_id']}` ({ns['topic']}) — Initial urgency: **{ns['urgency']}/100**")
            lines.append("")

        if changes["escalations"]:
            lines.append(f"### 📈 Escalated Stories ({len(changes['escalations'])})")
            for esc in changes["escalations"]:
                lines.append(
                    f"- Story `{esc['cluster_id']}` ({esc['topic']}): urgency jumped from "
                    f"**{esc['old_urgency']}** ➔ **{esc['new_urgency']}**"
                )
            lines.append("")

        if changes["new_evidence"]:
            lines.append(f"### 📑 Additional Corroborations & Evidence ({len(changes['new_evidence'])})")
            for ne in changes["new_evidence"][:5]:
                lines.append(
                    f"- Story `{ne['cluster_id']}` received new cross-source reports (now {ne['new_member_count']} members)"
                )
            lines.append("")

        if not changes["new_stories"] and not changes["escalations"] and not changes["new_evidence"]:
            lines.append("_No material state changes detected since the previous digest run._\n")

        lines.append("---")
        lines.append(
            "\n*Digest compiled automatically by Jyot Agentic Multimodal Monitor. "
            "All alert emissions strictly require explicit operator approval.*"
        )

        digest_text = "\n".join(lines)
        self.db.save_digest_run(run_id, len(ranked_clusters), digest_text)
        return digest_text

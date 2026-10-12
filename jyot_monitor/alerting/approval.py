"""Human approval workflow for proposed alerts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from jyot_monitor.database import Database
from jyot_monitor.schemas import ProposalSchema, ProposalStatus


class AlertApprovalService:
    """Handles review, approval, and rejection of alert proposals."""

    def __init__(self, db: Database, alerts_file: str = "reports/approved_alerts.jsonl"):
        self.db = db
        self.alerts_file = alerts_file
        Path(self.alerts_file).parent.mkdir(parents=True, exist_ok=True)

    def approve_proposal(
        self, proposal_id: str, reviewer: str = "operator"
    ) -> Tuple[bool, str, Optional[ProposalSchema]]:
        """Approves a proposal, marking it approved and appending to the local alerts file."""
        proposal = self.db.get_proposal(proposal_id)
        if not proposal:
            return False, f"Proposal '{proposal_id}' does not exist.", None

        if proposal.status == ProposalStatus.APPROVED:
            return True, f"Proposal '{proposal_id}' was already approved at {proposal.decision_timestamp}.", proposal

        if proposal.status == ProposalStatus.REJECTED:
            return False, f"Proposal '{proposal_id}' was previously rejected. Cannot re-approve.", proposal

        now = datetime.now(timezone.utc).isoformat()
        proposal.status = ProposalStatus.APPROVED
        proposal.decision_timestamp = now
        proposal.reviewer = reviewer

        self.db.save_proposal(proposal)

        # Emit to local alerts output sink
        alert_record = {
            "event": "alert_emitted",
            "proposal_id": proposal.proposal_id,
            "cluster_id": proposal.cluster_id,
            "item_id": proposal.item_id,
            "source_url": proposal.source_url,
            "evidence": proposal.redacted_evidence,
            "urgency_score": proposal.urgency_score,
            "relevance_score": proposal.relevance_score,
            "approved_by": reviewer,
            "approved_at": now,
        }
        with open(self.alerts_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert_record) + "\n")

        return True, f"Proposal '{proposal_id}' successfully approved and emitted to {self.alerts_file}.", proposal

    def reject_proposal(
        self, proposal_id: str, reviewer: str = "operator", reason: Optional[str] = None
    ) -> Tuple[bool, str, Optional[ProposalSchema]]:
        """Rejects a proposal."""
        proposal = self.db.get_proposal(proposal_id)
        if not proposal:
            return False, f"Proposal '{proposal_id}' does not exist.", None

        if proposal.status == ProposalStatus.REJECTED:
            return True, f"Proposal '{proposal_id}' was already rejected.", proposal

        now = datetime.now(timezone.utc).isoformat()
        proposal.status = ProposalStatus.REJECTED
        proposal.decision_timestamp = now
        proposal.reviewer = reviewer

        self.db.save_proposal(proposal)
        msg = f"Proposal '{proposal_id}' successfully rejected."
        if reason:
            msg += f" Reason: {reason}"
        return True, msg, proposal

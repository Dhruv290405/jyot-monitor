"""Proposal management for human-approval alert queue."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from jyot_monitor.database import Database
from jyot_monitor.safety.pii import PIIRedactor
from jyot_monitor.schemas import ProposalSchema, ProposalStatus, ScoringResult, ItemSchema


class ProposalManager:
    """Creates and manages persistent alert proposals."""

    def __init__(self, db: Database, redactor: Optional[PIIRedactor] = None):
        self.db = db
        self.redactor = redactor or PIIRedactor()

    def create_proposal(
        self,
        cluster_id: str,
        item: ItemSchema,
        scoring: ScoringResult,
        verification_status: str,
        supporting_sources: List[str],
        ocr_evidence_ref: Optional[str] = None,
        threshold_rationale: Optional[str] = None,
    ) -> ProposalSchema:
        """Creates a pending alert proposal with redacted evidence snippet."""
        proposal_id = f"prop_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()

        # Redact raw evidence
        raw_evidence = item.text or ""
        redacted_evidence, _ = self.redactor.redact(raw_evidence[:280])

        default_rationale = (
            f"Urgency score ({scoring.urgency_score}/100) exceeded alert threshold. "
            f"Source credibility: {item.source}. Verification: {verification_status}."
        )

        proposal = ProposalSchema(
            proposal_id=proposal_id,
            cluster_id=cluster_id,
            item_id=item.item_id,
            source_url=item.source_url,
            redacted_evidence=redacted_evidence,
            ocr_evidence_ref=ocr_evidence_ref,
            confidence=scoring.relevance_score,
            uncertainty_flags=scoring.uncertainty_flags,
            verification_status=verification_status,
            supporting_sources=supporting_sources,
            relevance_score=scoring.relevance_score,
            urgency_score=scoring.urgency_score,
            threshold_rationale=threshold_rationale or default_rationale,
            created_at=now,
            status=ProposalStatus.PENDING,
        )

        self.db.save_proposal(proposal)
        return proposal

    def get_proposal(self, proposal_id: str) -> Optional[ProposalSchema]:
        return self.db.get_proposal(proposal_id)

    def list_pending(self) -> List[ProposalSchema]:
        return self.db.list_proposals(status=ProposalStatus.PENDING)

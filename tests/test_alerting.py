"""Tests for alert proposals and human approval queue."""

import pytest
from pathlib import Path
from jyot_monitor.database import Database
from jyot_monitor.alerting.proposals import ProposalManager
from jyot_monitor.alerting.approval import AlertApprovalService
from jyot_monitor.schemas import ItemSchema, ProposalStatus, ScoringResult


@pytest.fixture
def test_setup(tmp_path):
    db = Database(db_path=str(tmp_path / "test.db"))
    alerts_file = tmp_path / "approved_alerts.jsonl"
    prop_mgr = ProposalManager(db=db)
    approval_svc = AlertApprovalService(db=db, alerts_file=str(alerts_file))
    return db, prop_mgr, approval_svc, alerts_file


def test_proposal_lifecycle(test_setup):
    db, prop_mgr, approval_svc, alerts_file = test_setup

    item = ItemSchema(
        item_id="item_alert_1",
        source="cpsc",
        source_url="https://cpsc.gov/alert",
        published_at="2026-10-01T00:00:00Z",
        text="Fire in heater model H-400. Contact user@test.com",
        content_hash="h_alert",
    )
    scoring = ScoringResult(
        relevance_score=95.0,
        urgency_score=88.0,
        llm_urgency=90.0,
        non_llm_urgency=35.0,
        uncertainty_flags=[],
    )

    # 1. Create proposal
    proposal = prop_mgr.create_proposal(
        cluster_id="cluster_1",
        item=item,
        scoring=scoring,
        verification_status="verified",
        supporting_sources=["cpsc"],
    )
    assert proposal.status == ProposalStatus.PENDING
    assert "[EMAIL_REDACTED]" in proposal.redacted_evidence

    # 2. Approve proposal
    success, msg, approved_prop = approval_svc.approve_proposal(
        proposal.proposal_id, reviewer="operator_alice"
    )
    assert success
    assert approved_prop.status == ProposalStatus.APPROVED
    assert approved_prop.reviewer == "operator_alice"
    assert approved_prop.decision_timestamp is not None

    # Check alert was emitted to local alerts file
    assert alerts_file.exists()
    content = alerts_file.read_text(encoding="utf-8")
    assert proposal.proposal_id in content

    # 3. Idempotent re-approval
    success_repeat, msg_repeat, _ = approval_svc.approve_proposal(
        proposal.proposal_id, reviewer="operator_bob"
    )
    assert success_repeat
    assert "already approved" in msg_repeat


def test_proposal_rejection(test_setup):
    db, prop_mgr, approval_svc, alerts_file = test_setup

    item = ItemSchema(
        item_id="item_alert_2",
        source="forum",
        source_url="https://forum.com",
        published_at="2026-10-01T00:00:00Z",
        text="Vague rumor about toy defect",
        content_hash="h_toy",
    )
    scoring = ScoringResult(
        relevance_score=50.0,
        urgency_score=72.0,
        llm_urgency=70.0,
        non_llm_urgency=10.0,
        uncertainty_flags=["unverified"],
    )

    proposal = prop_mgr.create_proposal(
        cluster_id="cluster_2",
        item=item,
        scoring=scoring,
        verification_status="unverified",
        supporting_sources=["forum"],
    )

    success, msg, rejected_prop = approval_svc.reject_proposal(
        proposal.proposal_id, reviewer="operator_alice", reason="Unverified single rumor"
    )
    assert success
    assert rejected_prop.status == ProposalStatus.REJECTED
    assert "Unverified single rumor" in msg

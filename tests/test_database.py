"""Tests for SQLite database persistence and caching."""

import pytest
from pathlib import Path
from jyot_monitor.database import Database
from jyot_monitor.schemas import ItemSchema, ProcessingStatus, ProposalSchema, ProposalStatus, StoryCluster


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test.db"
    return Database(db_path=str(db_file))


def test_seen_items_tracking(test_db):
    item = ItemSchema(
        item_id="item_001",
        source="fda",
        source_url="https://fda.gov/test",
        published_at="2026-10-01T00:00:00Z",
        text="Sample recall text",
        content_hash="hash_001",
        processing_status=ProcessingStatus.COMPLETED,
    )
    assert not test_db.is_item_seen("item_001")
    test_db.save_item(item)
    assert test_db.is_item_seen("item_001")

    retrieved = test_db.get_item("item_001")
    assert retrieved is not None
    assert retrieved.text == "Sample recall text"


def test_ocr_and_llm_cache(test_db):
    # OCR cache test
    test_db.set_ocr_cache("img_hash_1", "tesseract", "5.0", "standard", {"text": "hello ocr"})
    cached = test_db.get_ocr_cache("img_hash_1", "tesseract", "5.0", "standard")
    assert cached is not None
    assert cached["text"] == "hello ocr"

    # LLM cache test
    test_db.set_llm_cache("prompt_hash_1", "llama3.2", "classification response")
    llm_resp = test_db.get_llm_cache("prompt_hash_1", "llama3.2")
    assert llm_resp == "classification response"


def test_proposals_persistence(test_db):
    prop = ProposalSchema(
        proposal_id="prop_01",
        cluster_id="cluster_01",
        item_id="item_01",
        redacted_evidence="Dangerous heater [PHONE_REDACTED]",
        confidence=85.0,
        uncertainty_flags=[],
        verification_status="verified",
        supporting_sources=["cpsc"],
        relevance_score=90.0,
        urgency_score=85.0,
        threshold_rationale="Urgency exceeded threshold",
        created_at="2026-10-01T00:00:00Z",
        status=ProposalStatus.PENDING,
    )
    test_db.save_proposal(prop)
    fetched = test_db.get_proposal("prop_01")
    assert fetched is not None
    assert fetched.status == ProposalStatus.PENDING
    assert len(test_db.list_proposals(ProposalStatus.PENDING)) == 1

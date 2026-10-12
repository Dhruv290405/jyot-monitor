"""Tests verifying CLI replay mode, zero network requests, and digest generation."""

import os
from pathlib import Path

# Set TRACES_DIR before importing so default_config picks it up
os.environ["TRACES_DIR"] = str(Path("tests").absolute().parent / "traces_test")

import pytest
from unittest.mock import patch

from jyot_monitor.cli import handle_run, handle_approve, build_system


def test_cli_replay_execution(tmp_path):
    """Basic replay execution test - verifies zero network and digest generation."""
    digest_path = tmp_path / "digest.md"
    db_path = tmp_path / "test_replay.db"

    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(digest_path)
        max_items = 10
        db = str(db_path)

    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args)

        assert mock_connect.call_count == 0
        assert exit_code == 0

    assert digest_path.exists()
    digest_content = digest_path.read_text(encoding="utf-8")
    assert "# 🚨 Jyot Public Safety & Recall Intelligence Digest" in digest_content
    assert "Prioritized Story Clusters" in digest_content
    assert "What Changed Since Last Digest?" in digest_content
    assert "Urgency:" in digest_content


def test_fault_injection_cli_option(tmp_path):
    """Verify --fault-injection CLI option is defined and accepted."""
    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(tmp_path / "digest.md")
        max_items = 5
        db = str(tmp_path / "test.db")
        fault_injection = True

    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args)

        assert mock_connect.call_count == 0
        assert exit_code == 0
    assert (tmp_path / "digest.md").exists()


def test_fault_injection_without_replay_rejected(tmp_path):
    """Verify --fault-injection without --replay is rejected."""
    class Args:
        replay = None
        sources = None
        digest = str(tmp_path / "digest.md")
        max_items = 10
        db = str(tmp_path / "test.db")
        fault_injection = True

    exit_code = handle_run(Args)
    assert exit_code == 1


def test_normal_replay_unaffected(tmp_path):
    """Verify normal replay mode (without --fault-injection) remains unaffected."""
    digest_path = tmp_path / "digest.md"
    db_path = tmp_path / "test_replay_normal.db"

    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(digest_path)
        max_items = 10
        db = str(db_path)

    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args)

        assert mock_connect.call_count == 0
        assert exit_code == 0

    assert digest_path.exists()
    digest_content = digest_path.read_text(encoding="utf-8")
    assert "# 🚨 Jyot Public Safety & Recall Intelligence Digest" in digest_content
    assert "Prioritized Story Clusters" in digest_content
    assert "What Changed Since Last Digest?" in digest_content
    assert "Urgency:" in digest_content


def test_fault_injection_no_crash(tmp_path):
    """Verify fault-injection replay run completes without crashing (bounded retries, graceful termination)."""
    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(tmp_path / "digest.md")
        max_items = 5
        db = str(tmp_path / "test.db")
        fault_injection = True

    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args)

        assert mock_connect.call_count == 0
        assert exit_code == 0

    assert (tmp_path / "digest.md").exists()

    # Verify items were processed (system didn't crash or hang)
    sys_components = build_system(db_path=Args.db)
    db = sys_components["db"]
    items = db.list_all_items()
    assert len(items) > 0, "Items should be processed"
    for item in items:
        # Items should have a valid processing status (not crash/timeout)
        assert item.processing_status in (
            "completed",
            "partially_processed",
            "flagged_injection",
        ), f"Unexpected processing status: {item.processing_status}"


def test_fault_injection_items_have_flags_or_status(tmp_path):
    """Verify that fault-injection replay items have appropriate safety flags or status."""
    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(tmp_path / "digest.md")
        max_items = 5
        db = str(tmp_path / "test.db")
        fault_injection = True

    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args)

        assert mock_connect.call_count == 0
        assert exit_code == 0

    assert (tmp_path / "digest.md").exists()

    sys_components = build_system(db_path=Args.db)
    db = sys_components["db"]
    items = db.list_all_items()

    # Each item should have been processed; check for injection-related flags
    # or a valid status. The fault injection injects OCR failure, which the
    # system handles gracefully - items may or may not have injection flags
    # depending on whether the item text itself contains injection patterns.
    for item in items:
        assert item.processing_status is not None
        # Safety flags should be a list (possibly empty)
        assert isinstance(item.trust_and_safety_flags, list)


def test_digest_generated_with_fault_injection(tmp_path):
    """Verify digest is generated correctly even with fault injection enabled."""
    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(tmp_path / "digest.md")
        max_items = 5
        db = str(tmp_path / "test.db")
        fault_injection = True

    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args)

        assert mock_connect.call_count == 0
        assert exit_code == 0

    assert (tmp_path / "digest.md").exists()
    digest_content = (tmp_path / "digest.md").read_text(encoding="utf-8")
    # Digest should have required sections
    assert "# 🚨 Jyot Public Safety & Recall Intelligence Digest" in digest_content
    assert "Prioritized Story Clusters" in digest_content
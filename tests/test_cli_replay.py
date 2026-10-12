"""Tests verifying CLI replay mode, zero network requests, and digest generation."""

import subprocess
import sys
from pathlib import Path
import pytest
from unittest.mock import patch

from jyot_monitor.cli import handle_run, handle_approve, build_system


def test_cli_replay_execution(tmp_path):
    digest_path = tmp_path / "digest.md"
    db_path = tmp_path / "test_replay.db"

    class Args:
        replay = "data/sample_dataset"
        sources = None
        digest = str(digest_path)
        max_items = 10
        db = str(db_path)

    # Patch socket.socket.connect to enforce zero external network requests during replay
    with patch("socket.socket.connect") as mock_connect:
        exit_code = handle_run(Args())

        # Assert no network connections were established
        assert mock_connect.call_count == 0
        assert exit_code == 0

    assert digest_path.exists()
    digest_content = digest_path.read_text(encoding="utf-8")

    # Assert required sections exist in generated digest
    assert "# 🚨 Jyot Public Safety & Recall Intelligence Digest" in digest_content
    assert "Prioritized Story Clusters" in digest_content
    assert "What Changed Since Last Digest?" in digest_content
    assert "Urgency:" in digest_content


def test_approve_cli(tmp_path):
    digest_path = tmp_path / "digest.md"
    db_path = tmp_path / "test_approve.db"

    class RunArgs:
        replay = "data/sample_dataset"
        sources = None
        digest = str(digest_path)
        max_items = 10
        db = str(db_path)

    handle_run(RunArgs())

    # Check proposals in DB
    sys_components = build_system(db_path=str(db_path))
    proposals = sys_components["db"].list_proposals()

    if proposals:
        prop_id = proposals[0].proposal_id
        class ApproveArgs:
            proposal_id = prop_id
            reviewer = "test_operator"
            db = str(db_path)

        approve_code = handle_approve(ApproveArgs())
        assert approve_code == 0

        # Verify proposal status in DB is now approved
        updated_prop = sys_components["db"].get_proposal(prop_id)
        assert updated_prop.status.value == "approved"

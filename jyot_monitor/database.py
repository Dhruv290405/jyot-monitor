"""Persistent SQLite storage layer for Jyot Multimodal Monitor."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from jyot_monitor.schemas import (
    ItemSchema,
    ProposalSchema,
    ProposalStatus,
    StoryCluster,
    ProcessingStatus,
)


class Database:
    """Manages SQLite storage for items, caches, clusters, and proposals."""

    def __init__(self, db_path: str = "data/jyot_monitor.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        """Create necessary tables and indices."""
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS seen_items (
                    item_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_url TEXT,
                    published_at TEXT,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_cursors (
                    source_id TEXT PRIMARY KEY,
                    cursor_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ocr_cache (
                    cache_key TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    preprocessing_profile TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_cache (
                    prompt_hash TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS story_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    representative_item_id TEXT NOT NULL,
                    members_json TEXT NOT NULL,
                    max_urgency REAL DEFAULT 0.0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    source_url TEXT,
                    redacted_evidence TEXT NOT NULL,
                    ocr_evidence_ref TEXT,
                    confidence REAL DEFAULT 0.0,
                    uncertainty_flags_json TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    supporting_sources_json TEXT NOT NULL,
                    relevance_score REAL DEFAULT 0.0,
                    urgency_score REAL DEFAULT 0.0,
                    threshold_rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision_timestamp TEXT,
                    reviewer TEXT
                );

                CREATE TABLE IF NOT EXISTS digest_history (
                    run_id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    stories_count INTEGER NOT NULL,
                    digest_md TEXT NOT NULL
                );
                """
            )

    # --- Item & Seen Tracking ---

    def is_item_seen(self, item_id: str) -> bool:
        """Check if an item ID has already been ingested and completed."""
        cur = self.conn.cursor()
        cur.execute("SELECT status FROM seen_items WHERE item_id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            return False
        return row["status"] == ProcessingStatus.COMPLETED.value

    def get_item(self, item_id: str) -> Optional[ItemSchema]:
        """Retrieve an item by ID."""
        cur = self.conn.cursor()
        cur.execute("SELECT data_json FROM seen_items WHERE item_id = ?", (item_id,))
        row = cur.fetchone()
        if row:
            return ItemSchema.model_validate_json(row["data_json"])
        return None

    def save_item(self, item: ItemSchema) -> None:
        """Upsert an item record."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO seen_items (item_id, source, source_url, published_at, content_hash, status, data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    status = excluded.status,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    item.item_id,
                    item.source,
                    item.source_url,
                    item.published_at,
                    item.content_hash,
                    item.processing_status.value,
                    item.model_dump_json(),
                    now,
                    now,
                ),
            )

    def list_all_items(self) -> List[ItemSchema]:
        """Return all items."""
        cur = self.conn.cursor()
        cur.execute("SELECT data_json FROM seen_items")
        return [ItemSchema.model_validate_json(r["data_json"]) for r in cur.fetchall()]

    # --- Cursors ---

    def get_source_cursor(self, source_id: str) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT cursor_value FROM source_cursors WHERE source_id = ?", (source_id,))
        row = cur.fetchone()
        return row["cursor_value"] if row else None

    def set_source_cursor(self, source_id: str, cursor_value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO source_cursors (source_id, cursor_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    cursor_value = excluded.cursor_value,
                    updated_at = excluded.updated_at
                """,
                (source_id, cursor_value, now),
            )

    # --- OCR Cache ---

    def get_ocr_cache(
        self, content_hash: str, engine: str, engine_version: str, preprocessing_profile: str
    ) -> Optional[Dict[str, Any]]:
        cache_key = f"{content_hash}:{engine}:{engine_version}:{preprocessing_profile}"
        cur = self.conn.cursor()
        cur.execute("SELECT result_json FROM ocr_cache WHERE cache_key = ?", (cache_key,))
        row = cur.fetchone()
        if row:
            return json.loads(row["result_json"])
        return None

    def set_ocr_cache(
        self,
        content_hash: str,
        engine: str,
        engine_version: str,
        preprocessing_profile: str,
        result_dict: Dict[str, Any],
    ) -> None:
        cache_key = f"{content_hash}:{engine}:{engine_version}:{preprocessing_profile}"
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO ocr_cache
                (cache_key, content_hash, engine, engine_version, preprocessing_profile, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    content_hash,
                    engine,
                    engine_version,
                    preprocessing_profile,
                    json.dumps(result_dict),
                    now,
                ),
            )

    # --- LLM Cache ---

    def get_llm_cache(self, prompt_hash: str, model_name: str) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT response_text FROM llm_cache WHERE prompt_hash = ? AND model_name = ?",
            (prompt_hash, model_name),
        )
        row = cur.fetchone()
        return row["response_text"] if row else None

    def set_llm_cache(
        self,
        prompt_hash: str,
        model_name: str,
        response_text: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO llm_cache
                (prompt_hash, model_name, response_text, tokens_in, tokens_out, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (prompt_hash, model_name, response_text, tokens_in, tokens_out, now),
            )

    # --- Story Clusters ---

    def save_cluster(self, cluster: StoryCluster) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO story_clusters
                (cluster_id, topic, representative_item_id, members_json, max_urgency, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    representative_item_id = excluded.representative_item_id,
                    members_json = excluded.members_json,
                    max_urgency = excluded.max_urgency,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    cluster.cluster_id,
                    cluster.topic,
                    cluster.representative_item_id,
                    json.dumps(cluster.member_item_ids),
                    cluster.max_urgency,
                    cluster.status,
                    cluster.created_at,
                    cluster.updated_at,
                ),
            )

    def list_clusters(self) -> List[StoryCluster]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM story_clusters ORDER BY max_urgency DESC")
        results = []
        for r in cur.fetchall():
            results.append(
                StoryCluster(
                    cluster_id=r["cluster_id"],
                    topic=r["topic"],
                    representative_item_id=r["representative_item_id"],
                    member_item_ids=json.loads(r["members_json"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    max_urgency=r["max_urgency"],
                    status=r["status"],
                )
            )
        return results

    # --- Proposals Queue ---

    def save_proposal(self, proposal: ProposalSchema) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO proposals (
                    proposal_id, cluster_id, item_id, source_url, redacted_evidence,
                    ocr_evidence_ref, confidence, uncertainty_flags_json, verification_status,
                    supporting_sources_json, relevance_score, urgency_score, threshold_rationale,
                    created_at, status, decision_timestamp, reviewer
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    status = excluded.status,
                    decision_timestamp = excluded.decision_timestamp,
                    reviewer = excluded.reviewer
                """,
                (
                    proposal.proposal_id,
                    proposal.cluster_id,
                    proposal.item_id,
                    proposal.source_url,
                    proposal.redacted_evidence,
                    proposal.ocr_evidence_ref,
                    proposal.confidence,
                    json.dumps(proposal.uncertainty_flags),
                    proposal.verification_status,
                    json.dumps(proposal.supporting_sources),
                    proposal.relevance_score,
                    proposal.urgency_score,
                    proposal.threshold_rationale,
                    proposal.created_at,
                    proposal.status.value,
                    proposal.decision_timestamp,
                    proposal.reviewer,
                ),
            )

    def get_proposal(self, proposal_id: str) -> Optional[ProposalSchema]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,))
        r = cur.fetchone()
        if not r:
            return None
        return ProposalSchema(
            proposal_id=r["proposal_id"],
            cluster_id=r["cluster_id"],
            item_id=r["item_id"],
            source_url=r["source_url"],
            redacted_evidence=r["redacted_evidence"],
            ocr_evidence_ref=r["ocr_evidence_ref"],
            confidence=r["confidence"],
            uncertainty_flags=json.loads(r["uncertainty_flags_json"]),
            verification_status=r["verification_status"],
            supporting_sources=json.loads(r["supporting_sources_json"]),
            relevance_score=r["relevance_score"],
            urgency_score=r["urgency_score"],
            threshold_rationale=r["threshold_rationale"],
            created_at=r["created_at"],
            status=ProposalStatus(r["status"]),
            decision_timestamp=r["decision_timestamp"],
            reviewer=r["reviewer"],
        )

    def list_proposals(self, status: Optional[ProposalStatus] = None) -> List[ProposalSchema]:
        cur = self.conn.cursor()
        if status:
            cur.execute("SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC", (status.value,))
        else:
            cur.execute("SELECT * FROM proposals ORDER BY created_at DESC")
        results = []
        for r in cur.fetchall():
            results.append(
                ProposalSchema(
                    proposal_id=r["proposal_id"],
                    cluster_id=r["cluster_id"],
                    item_id=r["item_id"],
                    source_url=r["source_url"],
                    redacted_evidence=r["redacted_evidence"],
                    ocr_evidence_ref=r["ocr_evidence_ref"],
                    confidence=r["confidence"],
                    uncertainty_flags=json.loads(r["uncertainty_flags_json"]),
                    verification_status=r["verification_status"],
                    supporting_sources=json.loads(r["supporting_sources_json"]),
                    relevance_score=r["relevance_score"],
                    urgency_score=r["urgency_score"],
                    threshold_rationale=r["threshold_rationale"],
                    created_at=r["created_at"],
                    status=ProposalStatus(r["status"]),
                    decision_timestamp=r["decision_timestamp"],
                    reviewer=r["reviewer"],
                )
            )
        return results

    # --- Digest Run History ---

    def save_digest_run(self, run_id: str, stories_count: int, digest_md: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO digest_history (run_id, generated_at, stories_count, digest_md)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, now, stories_count, digest_md),
            )

    def get_latest_digest(self) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM digest_history ORDER BY generated_at DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            return dict(row)
        return None

    def close(self) -> None:
        self.conn.close()

"""Data schemas and contracts for Jyot Multimodal Monitor."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    """Lifecycle status for an ingested item."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_PROCESSED = "partially_processed"
    FAILED = "failed"
    FLAGGED_INJECTION = "flagged_injection"


class AttachmentType(str, Enum):
    """Type of attachment."""
    IMAGE = "image"
    PDF = "pdf"
    UNKNOWN = "unknown"


class ProposalStatus(str, Enum):
    """Status of an alert proposal."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AttachmentRef(BaseModel):
    """Reference to an attachment (local or URL)."""
    ref: str
    attachment_type: AttachmentType = AttachmentType.UNKNOWN
    sha256: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int = 0
    resolved_local_path: Optional[str] = None


class ItemSchema(BaseModel):
    """Common, validated item schema required by Stage A."""
    item_id: str
    source: str
    source_url: Optional[str] = None
    published_at: Optional[str] = None
    text: str = ""
    attachments: List[AttachmentRef] = Field(default_factory=list)
    attachment_type: AttachmentType = AttachmentType.UNKNOWN
    content_hash: str = ""
    ingestion_timestamp: Optional[str] = None
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    language: Optional[str] = None
    trust_and_safety_flags: List[str] = Field(default_factory=list)
    raw_payload: Optional[Dict[str, Any]] = None


class OCRExtractResult(BaseModel):
    """Standardized OCR extraction result required by Stage C."""
    engine: str
    engine_version: str = "1.0"
    text: str = ""
    confidence: float = 0.0  # Normalized 0.0 - 100.0
    raw_confidence: Optional[float] = None
    language: str = "en"
    preprocessing_profile: str = "standard"
    needs_second_opinion: bool = False
    router_decision: str = "engine_selected"
    router_rationale: str = ""
    page_number: Optional[int] = 1
    total_pages: Optional[int] = 1
    layout_hints: Dict[str, Any] = Field(default_factory=dict)
    is_fallback: bool = False
    error: Optional[str] = None
    latency_seconds: float = 0.0
    cost_estimate_usd: float = 0.0


class StructuredNotice(BaseModel):
    """Structured extraction schema for public safety & recall notices."""
    organization: Optional[str] = None
    notice_type: Optional[str] = None
    product_or_subject: Optional[str] = None
    batch_or_reference_number: Optional[str] = None
    date: Optional[str] = None
    location: Optional[str] = None
    action_required: Optional[str] = None
    supporting_evidence: Optional[str] = None
    uncertainty_flags: List[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    """Topic taxonomy classification."""
    subtopic: str
    confidence: float
    explanation: str


class ScoringResult(BaseModel):
    """Dual relevance & urgency scoring result."""
    relevance_score: float = Field(ge=0.0, le=100.0)
    urgency_score: float = Field(ge=0.0, le=100.0)
    llm_urgency: float = 0.0
    non_llm_urgency: float = 0.0
    evidence_snippets: List[str] = Field(default_factory=list)
    breakdown: Dict[str, float] = Field(default_factory=dict)
    uncertainty_flags: List[str] = Field(default_factory=list)


class ProposalSchema(BaseModel):
    """Human approval alert proposal required by Stage H."""
    proposal_id: str
    cluster_id: str
    item_id: str
    source_url: Optional[str] = None
    redacted_evidence: str
    ocr_evidence_ref: Optional[str] = None
    confidence: float = 0.0
    uncertainty_flags: List[str] = Field(default_factory=list)
    verification_status: str = "unverified"
    supporting_sources: List[str] = Field(default_factory=list)
    relevance_score: float = 0.0
    urgency_score: float = 0.0
    threshold_rationale: str = ""
    created_at: str
    status: ProposalStatus = ProposalStatus.PENDING
    decision_timestamp: Optional[str] = None
    reviewer: Optional[str] = None


class StoryCluster(BaseModel):
    """Story cluster grouping duplicate & related items."""
    cluster_id: str
    topic: str
    representative_item_id: str
    member_item_ids: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    max_urgency: float = 0.0
    status: str = "active"


class AgentAction(BaseModel):
    """Planner decision for the next tool call."""
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class AgentTraceStep(BaseModel):
    """JSONL trace event required by Stage E."""
    run_id: str
    item_id: str
    step_number: int
    timestamp: str
    planner_model: str
    chosen_action: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    decision_rationale: str = ""
    success: bool = True
    error_type: Optional[str] = None
    latency_seconds: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: float = 0.0
    cumulative_item_budget_usd: float = 0.0
    cumulative_run_budget_usd: float = 0.0
    ocr_engine: Optional[str] = None
    router_rationale: Optional[str] = None
    is_fallback: bool = False

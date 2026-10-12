"""Typed agent tools with permission checks, isolation, and schema contracts."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from jyot_monitor.database import Database
from jyot_monitor.extraction.pdf import PDFProcessor
from jyot_monitor.extraction.router import OCRRouter
from jyot_monitor.extraction.vision_engine import VisionEngine
from jyot_monitor.intelligence.classification import TopicClassifier
from jyot_monitor.intelligence.scoring import PriorityScorer
from jyot_monitor.intelligence.verification import UrgencyVerifier
from jyot_monitor.alerting.proposals import ProposalManager
from jyot_monitor.safety.network import SafeFetcher
from jyot_monitor.schemas import (
    ItemSchema,
    OCRExtractResult,
    ProposalSchema,
    ScoringResult,
    ClassificationResult,
)

logger = logging.getLogger(__name__)


# --- Typed Tool Request & Response Schemas ---

class FetchAttachmentInput(BaseModel):
    url: str


class FetchAttachmentOutput(BaseModel):
    success: bool
    local_path: Optional[str] = None
    mime_type: Optional[str] = None
    error: Optional[str] = None


class OCRExtractInput(BaseModel):
    attachment_index: int = 0
    language_hint: Optional[str] = "en"
    profile: Optional[str] = "standard"
    force_engine: Optional[str] = None


class OCRExtractOutput(BaseModel):
    success: bool
    text: str = ""
    confidence: float = 0.0
    engine: str = ""
    needs_second_opinion: bool = False
    router_rationale: str = ""
    error: Optional[str] = None


class VisionDescribeInput(BaseModel):
    attachment_index: int = 0
    prompt: Optional[str] = None


class VisionDescribeOutput(BaseModel):
    success: bool
    description: str = ""
    error: Optional[str] = None


class SearchMemoryInput(BaseModel):
    query: str


class SearchMemoryOutput(BaseModel):
    matches_count: int
    matched_items: List[Dict[str, Any]] = Field(default_factory=list)


class VerifyClaimInput(BaseModel):
    claim_summary: str


class VerifyClaimOutput(BaseModel):
    is_verified: bool
    adjusted_urgency: float
    flags: List[str] = Field(default_factory=list)
    explanation: str = ""


class ProposeAlertInput(BaseModel):
    rationale: str


class ProposeAlertOutput(BaseModel):
    success: bool
    proposal_id: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None


class ToolRegistry:
    """Manages tool execution, permission gating, and environment isolation."""

    def __init__(
        self,
        db: Database,
        router: OCRRouter,
        vision_engine: VisionEngine,
        classifier: TopicClassifier,
        scorer: PriorityScorer,
        verifier: UrgencyVerifier,
        proposal_manager: ProposalManager,
        safe_fetcher: SafeFetcher,
        pdf_processor: PDFProcessor,
        is_replay_mode: bool = False,
    ):
        self.db = db
        self.router = router
        self.vision = vision_engine
        self.classifier = classifier
        self.scorer = scorer
        self.verifier = verifier
        self.proposal_manager = proposal_manager
        self.safe_fetcher = safe_fetcher
        self.pdf_processor = pdf_processor
        self.is_replay_mode = is_replay_mode

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context_item: ItemSchema,
        cluster_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Dispatches tool execution with strict permission enforcement."""

        # Tool 1: fetch_attachment
        if tool_name == "fetch_attachment":
            if self.is_replay_mode:
                return FetchAttachmentOutput(
                    success=False,
                    error="fetch_attachment permission DENIED in replay mode: zero network requests guaranteed.",
                ).model_dump()

            try:
                args = FetchAttachmentInput.model_validate(arguments)
                saved_path, mime_type, _ = self.safe_fetcher.fetch(args.url)
                return FetchAttachmentOutput(
                    success=True, local_path=saved_path, mime_type=mime_type
                ).model_dump()
            except Exception as e:
                return FetchAttachmentOutput(success=False, error=str(e)).model_dump()

        # Tool 2: ocr_extract
        elif tool_name == "ocr_extract":
            try:
                args = OCRExtractInput.model_validate(arguments)
                if not context_item.attachments or args.attachment_index >= len(context_item.attachments):
                    return OCRExtractOutput(
                        success=False,
                        error=f"Attachment index {args.attachment_index} out of range (total {len(context_item.attachments)}).",
                    ).model_dump()

                att = context_item.attachments[args.attachment_index]
                img_path = att.resolved_local_path or att.ref

                # Check if it's a PDF
                if att.attachment_type.value == "pdf" or str(img_path).lower().endswith(".pdf"):
                    try:
                        rendered_img = self.pdf_processor.render_page(img_path, page_number=1)
                        ocr_res = self.router.route_and_extract(
                            rendered_img,
                            language_hint=args.language_hint,
                            force_engine=args.force_engine,
                        )
                    except Exception as pe:
                        return OCRExtractOutput(
                            success=False, error=f"PDF rendering error: {pe}"
                        ).model_dump()
                else:
                    ocr_res = self.router.route_and_extract(
                        img_path,
                        language_hint=args.language_hint,
                        force_engine=args.force_engine,
                    )

                # Store OCR result in state
                state["ocr_result"] = ocr_res
                return OCRExtractOutput(
                    success=True,
                    text=ocr_res.text,
                    confidence=ocr_res.confidence,
                    engine=ocr_res.engine,
                    needs_second_opinion=ocr_res.needs_second_opinion,
                    router_rationale=ocr_res.router_rationale,
                    error=ocr_res.error,
                ).model_dump()
            except Exception as e:
                return OCRExtractOutput(success=False, error=str(e)).model_dump()

        # Tool 3: vision_describe
        elif tool_name == "vision_describe":
            try:
                args = VisionDescribeInput.model_validate(arguments)
                if not context_item.attachments or args.attachment_index >= len(context_item.attachments):
                    return VisionDescribeOutput(
                        success=False, error="No valid attachment found at index."
                    ).model_dump()

                att = context_item.attachments[args.attachment_index]
                img_path = att.resolved_local_path or att.ref
                if att.attachment_type.value == "pdf" or str(img_path).lower().endswith(".pdf"):
                    rendered_img = self.pdf_processor.render_page(img_path, page_number=1)
                    desc = self.vision.describe_visuals(rendered_img, prompt=args.prompt)
                else:
                    desc = self.vision.describe_visuals(img_path, prompt=args.prompt)

                state["vision_description"] = desc
                return VisionDescribeOutput(success=True, description=desc).model_dump()
            except Exception as e:
                return VisionDescribeOutput(success=False, error=str(e)).model_dump()

        # Tool 4: search_memory
        elif tool_name == "search_memory":
            try:
                args = SearchMemoryInput.model_validate(arguments)
                all_items = self.db.list_all_items()
                query_lower = args.query.lower()
                matches = []
                for it in all_items:
                    if it.item_id != context_item.item_id and query_lower in it.text.lower():
                        matches.append({
                            "item_id": it.item_id,
                            "source": it.source,
                            "snippet": it.text[:120],
                        })
                return SearchMemoryOutput(
                    matches_count=len(matches), matched_items=matches[:5]
                ).model_dump()
            except Exception as e:
                return SearchMemoryOutput(matches_count=0, matched_items=[]).model_dump()

        # Tool 5: verify_claim
        elif tool_name == "verify_claim":
            try:
                args = VerifyClaimInput.model_validate(arguments)
                current_scoring: ScoringResult = state.get(
                    "scoring",
                    self.scorer.score(
                        context_item.text,
                        source=context_item.source,
                        published_at=context_item.published_at,
                    ),
                )
                all_items = self.db.list_all_items()
                is_ver, adj_urgency, flags, expl = self.verifier.critique_claim(
                    context_item, current_scoring, all_items
                )
                state["verification_status"] = "verified" if is_ver else "unverified"
                state["urgency_score"] = adj_urgency
                state["verification_flags"] = flags
                return VerifyClaimOutput(
                    is_verified=is_ver,
                    adjusted_urgency=adj_urgency,
                    flags=flags,
                    explanation=expl,
                ).model_dump()
            except Exception as e:
                return VerifyClaimOutput(
                    is_verified=False,
                    adjusted_urgency=state.get("urgency_score", 50.0),
                    flags=["verification_error"],
                    explanation=str(e),
                ).model_dump()

        # Tool 6: propose_alert
        elif tool_name == "propose_alert":
            try:
                args = ProposeAlertInput.model_validate(arguments)
                scoring: ScoringResult = state.get(
                    "scoring",
                    self.scorer.score(
                        context_item.text,
                        source=context_item.source,
                        published_at=context_item.published_at,
                    ),
                )
                ver_status = state.get("verification_status", "unverified")
                proposal = self.proposal_manager.create_proposal(
                    cluster_id=cluster_id,
                    item=context_item,
                    scoring=scoring,
                    verification_status=ver_status,
                    supporting_sources=[context_item.source],
                    ocr_evidence_ref=state.get("ocr_result", {}).get("engine") if isinstance(state.get("ocr_result"), dict) else None,
                    threshold_rationale=args.rationale,
                )
                state["proposal_created"] = proposal.proposal_id
                return ProposeAlertOutput(
                    success=True, proposal_id=proposal.proposal_id, status="pending"
                ).model_dump()
            except Exception as e:
                return ProposeAlertOutput(success=False, error=str(e)).model_dump()

        # Tool 7: finish
        elif tool_name == "finish":
            return {"success": True, "status": "completed"}

        else:
            return {"success": False, "error": f"Unknown tool requested: '{tool_name}'"}

"""Agent controller loop orchestrating planner, tools, budgets, and traces."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from jyot_monitor.agent.planner import LLMPlanner
from jyot_monitor.agent.tools import ToolRegistry
from jyot_monitor.agent.trace import TraceLogger
from jyot_monitor.safety.injection import InjectionDetector
from jyot_monitor.safety.spam import SpamDetector
from jyot_monitor.schemas import (
    AgentTraceStep,
    ItemSchema,
    ProcessingStatus,
    ScoringResult,
)


class AgentController:
    """Controls step-by-step execution of the agent loop with budget enforcement."""

    def __init__(
        self,
        planner: LLMPlanner,
        tools: ToolRegistry,
        tracer: TraceLogger,
        injection_detector: Optional[InjectionDetector] = None,
        spam_detector: Optional[SpamDetector] = None,
        max_steps_per_item: int = 6,
        item_budget_usd: float = 0.05,
        run_budget_usd: float = 1.00,
    ):
        self.planner = planner
        self.tools = tools
        self.tracer = tracer
        self.injection_detector = injection_detector or InjectionDetector()
        self.spam_detector = spam_detector or SpamDetector()
        self.max_steps = max_steps_per_item
        self.item_budget_usd = item_budget_usd
        self.run_budget_usd = run_budget_usd

        self.cumulative_run_cost_usd = 0.0

    def process_item(
        self,
        item: ItemSchema,
        cluster_id: str,
    ) -> Tuple[ProcessingStatus, Dict[str, Any]]:
        """Processes a single item through the genuine agent loop."""
        cumulative_item_cost_usd = 0.0
        step_history: List[Dict[str, Any]] = []
        state: Dict[str, Any] = {}

        # 1. Pre-execution Safety Scans
        is_inj, inj_reasons = self.injection_detector.scan(item.text)
        if is_inj:
            item.trust_and_safety_flags.extend([f"injection_{r}" for r in inj_reasons])
            item.processing_status = ProcessingStatus.FLAGGED_INJECTION

        is_spam, spam_flags = self.spam_detector.evaluate(item.text)
        if is_spam:
            item.trust_and_safety_flags.extend([f"spam_{f}" for f in spam_flags])

        # Initial baseline scoring
        initial_scoring = self.tools.scorer.score(
            item.text,
            source=item.source,
            published_at=item.published_at,
        )
        state["scoring"] = initial_scoring
        state["urgency_score"] = initial_scoring.urgency_score
        state["relevance_score"] = initial_scoring.relevance_score

        # Agent Step Loop
        for step_num in range(1, self.max_steps + 1):
            # Check budgets
            if cumulative_item_cost_usd >= self.item_budget_usd:
                item.processing_status = ProcessingStatus.PARTIALLY_PROCESSED
                self._record_trace(
                    item.item_id,
                    step_num,
                    "budget_limit_reached",
                    {},
                    "Item budget exhausted; marked partially_processed",
                    "Budget guard triggered",
                    False,
                    0.0,
                    cumulative_item_cost_usd,
                    is_fallback=True,
                )
                break

            if self.cumulative_run_cost_usd >= self.run_budget_usd:
                item.processing_status = ProcessingStatus.PARTIALLY_PROCESSED
                self._record_trace(
                    item.item_id,
                    step_num,
                    "run_budget_exceeded",
                    {},
                    "Global run budget exhausted; marked partially_processed",
                    "Run budget guard triggered",
                    False,
                    0.0,
                    cumulative_item_cost_usd,
                    is_fallback=True,
                )
                break

            # Planner decides next action
            start_time = time.time()
            action, is_fallback, model_or_reason = self.planner.decide_next_action(
                item, step_num, step_history, state
            )

            # Check stop condition
            if action.tool == "finish":
                step_latency = time.time() - start_time
                self._record_trace(
                    item.item_id,
                    step_num,
                    "finish",
                    action.arguments,
                    "Agent concluded investigation",
                    action.rationale,
                    True,
                    step_latency,
                    cumulative_item_cost_usd,
                    planner_model=model_or_reason,
                    is_fallback=is_fallback,
                )
                if item.processing_status != ProcessingStatus.FLAGGED_INJECTION:
                    item.processing_status = ProcessingStatus.COMPLETED
                break

            # Execute chosen tool
            tool_start = time.time()
            tool_output = self.tools.execute_tool(
                action.tool,
                action.arguments,
                item,
                cluster_id,
                state,
            )
            step_latency = time.time() - tool_start

            # Calculate cost estimate
            step_cost = 0.0005 if action.tool in ("ocr_extract", "vision_describe") else 0.0001
            cumulative_item_cost_usd += step_cost
            self.cumulative_run_cost_usd += step_cost

            # Record in history
            step_history.append({
                "step": step_num,
                "tool": action.tool,
                "summary": str(tool_output)[:100],
            })

            # Check for OCR-derived injection
            ocr_text = state.get("ocr_result", {}).text if hasattr(state.get("ocr_result"), "text") else ""
            if ocr_text:
                is_ocr_inj, ocr_inj_reasons = self.injection_detector.scan(ocr_text)
                if is_ocr_inj:
                    item.trust_and_safety_flags.extend([f"ocr_injection_{r}" for r in ocr_inj_reasons])
                    item.trust_and_safety_flags = list(set(item.trust_and_safety_flags))

            # Log trace step
            self._record_trace(
                item.item_id,
                step_num,
                action.tool,
                action.arguments,
                str(tool_output)[:120],
                action.rationale,
                tool_output.get("success", True),
                step_latency,
                cumulative_item_cost_usd,
                planner_model=model_or_reason,
                is_fallback=is_fallback,
                ocr_engine=getattr(state.get("ocr_result"), "engine", None),
                router_rationale=getattr(state.get("ocr_result"), "router_rationale", None),
            )

        if item.processing_status == ProcessingStatus.PENDING:
            item.processing_status = ProcessingStatus.COMPLETED

        return item.processing_status, state

    def _record_trace(
        self,
        item_id: str,
        step_number: int,
        tool: str,
        arguments: Dict[str, Any],
        summary: str,
        rationale: str,
        success: bool,
        latency: float,
        item_cost: float,
        planner_model: str = "controller",
        is_fallback: bool = False,
        ocr_engine: Optional[str] = None,
        router_rationale: Optional[str] = None,
    ) -> None:
        """Helper to create and append trace event."""
        trace = AgentTraceStep(
            run_id=self.tracer.run_id,
            item_id=item_id,
            step_number=step_number,
            timestamp=datetime.now(timezone.utc).isoformat(),
            planner_model=planner_model,
            chosen_action=tool,
            arguments=arguments,
            result_summary=summary,
            decision_rationale=rationale,
            success=success,
            latency_seconds=round(latency, 3),
            cost_usd=round(0.0002, 6),
            cumulative_item_budget_usd=round(item_cost, 6),
            cumulative_run_budget_usd=round(self.cumulative_run_cost_usd, 6),
            ocr_engine=ocr_engine,
            router_rationale=router_rationale,
            is_fallback=is_fallback,
        )
        self.tracer.log_step(trace)

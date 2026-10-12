"""LLM-driven planner with bounded retries and deterministic fallback."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import ValidationError

from jyot_monitor.agent.prompts import PLANNER_SYSTEM_PROMPT
from jyot_monitor.schemas import AgentAction, ItemSchema

logger = logging.getLogger(__name__)


class LLMPlanner:
    """Plans next tool action using a local LLM or deterministic fallback."""

    ALLOWED_TOOLS = {
        "ocr_extract",
        "vision_describe",
        "search_memory",
        "verify_claim",
        "propose_alert",
        "finish",
    }

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "llama3.2",
        timeout_seconds: float = 12.0,
        max_retries: int = 2,
        is_replay_mode: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.is_replay_mode = is_replay_mode
        self._llm_available: Optional[bool] = None

    def check_llm_available(self) -> bool:
        """Check if local Ollama model is available."""
        if self.is_replay_mode:
            return False
        if self._llm_available is not None:
            return self._llm_available
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=1.0)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                self._llm_available = any(self.model_name in m for m in models)
                return self._llm_available
        except Exception:
            pass
        self._llm_available = False
        return False

    def decide_next_action(
        self,
        item: ItemSchema,
        step_number: int,
        history: List[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> Tuple[AgentAction, bool, str]:
        """Plans the next action.

        Returns (action, is_fallback, model_or_reason).
        """
        # If model is not available, execute deterministic expert planner
        if not self.check_llm_available():
            action = self._deterministic_plan(item, step_number, history, state)
            return action, True, "deterministic_expert_fallback"

        # Construct prompt for LLM
        prompt = self._build_prompt(item, step_number, history, state)

        # Retry loop for LLM response
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model_name,
                        "system": PLANNER_SYSTEM_PROMPT,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1},
                    },
                    timeout=self.timeout_seconds,
                )

                if resp.status_code == 200:
                    raw_text = resp.json().get("response", "").strip()
                    parsed_json = json.loads(raw_text)
                    action = AgentAction.model_validate(parsed_json)

                    # Validate tool allow-list
                    if action.tool not in self.ALLOWED_TOOLS:
                        raise ValueError(f"Disallowed tool requested: {action.tool}")

                    return action, False, self.model_name

            except Exception as e:
                logger.warning(f"Planner LLM attempt {attempt+1} failed: {e}")

        # Fallback if LLM retries exhausted
        action = self._deterministic_plan(item, step_number, history, state)
        return action, True, f"fallback_after_{self.max_retries}_llm_failures"

    def _build_prompt(
        self,
        item: ItemSchema,
        step_number: int,
        history: List[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> str:
        """Constructs sanitized prompt context."""
        hist_summary = [
            f"Step {h['step']}: tool='{h['tool']}', result='{str(h['summary'])[:80]}'"
            for h in history
        ]
        return (
            f"Current Step: {step_number}\n"
            f"Item ID: {item.item_id}\n"
            f"Source: {item.source}\n"
            f"Has Attachments: {len(item.attachments)} attachments\n"
            f"Item Text Snippet: {item.text[:140]}\n"
            f"Execution History: {hist_summary}\n"
            f"Current State: {list(state.keys())}\n"
            "Choose the next tool."
        )

    def _deterministic_plan(
        self,
        item: ItemSchema,
        step_number: int,
        history: List[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> AgentAction:
        """Deterministic policy adhering to Stage D variable trajectories."""
        executed_tools = {h["tool"] for h in history}

        # 1. If item has attachments and OCR hasn't been run yet -> Run OCR
        if item.attachments and "ocr_extract" not in executed_tools:
            return AgentAction(
                tool="ocr_extract",
                arguments={"attachment_index": 0, "language_hint": item.language or "en"},
                rationale="Item has visual attachment; running OCR extraction.",
            )

        # 2. If OCR needs second opinion and vision hasn't run -> Run vision_describe
        ocr_res = state.get("ocr_result")
        ocr_needs_second = False
        if ocr_res:
            ocr_needs_second = getattr(ocr_res, "needs_second_opinion", False) or (
                getattr(ocr_res, "confidence", 100.0) < 60.0
            )

        if ocr_needs_second and "vision_describe" not in executed_tools:
            return AgentAction(
                tool="vision_describe",
                arguments={"attachment_index": 0, "prompt": "Describe this notice and verify contents."},
                rationale="OCR confidence is low or flagged needs_second_opinion; querying vision engine.",
            )

        # 3. High urgency check -> Verify claim before proposal
        urgency = state.get("urgency_score", 0.0)
        if urgency >= 75.0 and "verify_claim" not in executed_tools:
            return AgentAction(
                tool="verify_claim",
                arguments={"claim_summary": item.text[:120]},
                rationale="High urgency item (>=75); executing independent verification before proposal.",
            )

        # 4. If verified high urgency and no proposal created -> Propose alert
        if (
            urgency >= 70.0
            and state.get("verification_status") == "verified"
            and "propose_alert" not in executed_tools
        ):
            return AgentAction(
                tool="propose_alert",
                arguments={"rationale": f"Verified critical safety notice with urgency {urgency}/100."},
                rationale="Item verified and meets threshold; proposing alert to human approval queue.",
            )

        # 5. Otherwise, search memory if not done and high relevance
        if "search_memory" not in executed_tools and state.get("relevance_score", 0.0) >= 80.0:
            return AgentAction(
                tool="search_memory",
                arguments={"query": item.text[:40]},
                rationale="High relevance notice; checking database memory for prior related incidents.",
            )

        # 6. Stop condition reached
        return AgentAction(
            tool="finish",
            arguments={},
            rationale="All necessary inspection and scoring steps completed.",
        )

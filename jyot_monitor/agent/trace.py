"""Structured JSONL tracing and cost accounting for agent executions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from jyot_monitor.schemas import AgentTraceStep
from jyot_monitor.safety.pii import PIIRedactor


class TraceLogger:
    """Logs and manages execution traces in JSONL format."""

    def __init__(self, trace_dir: str = "traces", run_id: Optional[str] = None):
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self.trace_file = self.trace_dir / f"{self.run_id}.jsonl"
        self.redactor = PIIRedactor()
        self.steps: List[AgentTraceStep] = []

    def log_step(self, step: AgentTraceStep) -> None:
        """Appends a trace step to the JSONL log file with PII redacted from summaries."""
        # Ensure PII is not leaked into trace summaries
        clean_summary, _ = self.redactor.redact(step.result_summary)
        step.result_summary = clean_summary

        self.steps.append(step)
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(step.model_dump_json() + "\n")

    def get_traces_for_item(self, item_id: str) -> List[AgentTraceStep]:
        """Returns all trace steps for a specific item."""
        return [s for s in self.steps if s.item_id == item_id]

    def read_all_traces(self) -> List[AgentTraceStep]:
        """Reads all trace events from the JSONL file."""
        if not self.trace_file.exists():
            return []
        traces = []
        with open(self.trace_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    traces.append(AgentTraceStep.model_validate_json(line))
        return traces

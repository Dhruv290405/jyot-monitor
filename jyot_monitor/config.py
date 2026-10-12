"""Configuration management for Jyot Multimodal Monitor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load from .env if present
load_dotenv()


class AppConfig(BaseModel):
    """Global configuration settings."""

    # Storage paths
    database_path: str = Field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "data/jyot_monitor.db")
    )
    traces_dir: str = Field(
        default_factory=lambda: os.getenv("TRACES_DIR", "traces")
    )
    reports_dir: str = Field(
        default_factory=lambda: os.getenv("REPORTS_DIR", "reports")
    )
    fixtures_dir: str = Field(
        default_factory=lambda: os.getenv("FIXTURES_DIR", "fixtures")
    )

    # Local Ollama / LLM configuration
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    planner_model: str = Field(
        default_factory=lambda: os.getenv("PLANNER_MODEL", "llama3.2")
    )
    vision_model: str = Field(
        default_factory=lambda: os.getenv("VISION_MODEL", "llava")
    )
    llm_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "12.0"))
    )
    llm_temperature: float = Field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.1"))
    )

    # OCR settings
    tesseract_cmd: str = Field(
        default_factory=lambda: os.getenv("TESSERACT_CMD", "tesseract")
    )
    ocr_confidence_threshold: float = Field(
        default_factory=lambda: float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "60.0"))
    )
    ocr_preprocessing_profile: str = Field(
        default_factory=lambda: os.getenv("OCR_PREPROCESSING_PROFILE", "standard")
    )

    # Agent constraints & budgets
    max_steps_per_item: int = Field(
        default_factory=lambda: int(os.getenv("MAX_STEPS_PER_ITEM", "6"))
    )
    item_budget_usd: float = Field(
        default_factory=lambda: float(os.getenv("ITEM_BUDGET_USD", "0.05"))
    )
    run_budget_usd: float = Field(
        default_factory=lambda: float(os.getenv("RUN_BUDGET_USD", "1.00"))
    )
    urgency_threshold_for_alert: float = Field(
        default_factory=lambda: float(os.getenv("URGENCY_THRESHOLD_FOR_ALERT", "75.0"))
    )

    # Network safety
    max_attachment_size_mb: int = Field(
        default_factory=lambda: int(os.getenv("MAX_ATTACHMENT_SIZE_MB", "10"))
    )
    fetch_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("FETCH_TIMEOUT_SECONDS", "8.0"))
    )
    max_redirects: int = Field(
        default_factory=lambda: int(os.getenv("MAX_REDIRECTS", "3"))
    )
    allowed_schemes: List[str] = Field(
        default_factory=lambda: [s.strip() for s in os.getenv("ALLOWED_SCHEMES", "http,https").split(",") if s.strip()]
    )

    # Fault injection mode
    fault_injection_enabled: bool = False

    @property
    def ollama_planner_model(self) -> str:
        return self.planner_model

    @property
    def ollama_vision_model(self) -> str:
        return self.vision_model

    @property
    def agent_step_timeout_seconds(self) -> float:
        return self.llm_timeout_seconds

    @property
    def max_cost_per_item_usd(self) -> float:
        return self.item_budget_usd

    @property
    def max_cost_per_run_usd(self) -> float:
        return self.run_budget_usd

    @property
    def trace_dir(self) -> str:
        return self.traces_dir

    @property
    def alert_urgency_threshold(self) -> float:
        return self.urgency_threshold_for_alert

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        for path_str in [
            os.path.dirname(self.database_path) if os.path.dirname(self.database_path) else "data",
            self.traces_dir,
            self.reports_dir,
        ]:
            if path_str:
                Path(path_str).mkdir(parents=True, exist_ok=True)


default_config = AppConfig()


def get_config() -> AppConfig:
    """Returns singleton AppConfig."""
    return default_config


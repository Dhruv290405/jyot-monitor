"""Relevance and urgency scoring combining LLM/content judgment with non-LLM signals."""

from __future__ import annotations

import re
from typing import Dict, List, Optional
from datetime import datetime, timezone

from jyot_monitor.schemas import ScoringResult


class PriorityScorer:
    """Computes transparent, bounded relevance and urgency scores."""

    # Keywords indicating severity of physical/civic hazard
    HIGH_SEVERITY_PATTERNS = [
        r"(?i)\b(fatal|death|died|lethal|life-threatening|hospitaliz|infant\s+death)\b",
        r"(?i)\b(explosion|battery\s+fire|structural\s+collapse|severe\s+burn)\b",
        r"(?i)\b(botulism|cyanide|toxic\s+gas|chlorine\s+leak|class\s*i\s*recall)\b",
    ]
    MEDIUM_SEVERITY_PATTERNS = [
        r"(?i)\b(injury|choking\s+hazard|listeria|salmonella|e\.?\s*coli|boil\s+water)\b",
        r"(?i)\b(undeclared\s+peanut|allergic\s+reaction|faulty\s+brake|airbag)\b",
        r"(?i)\b(class\s*ii\s*recall|water\s+main\s+break|grid\s+blackout)\b",
    ]
    LOW_SEVERITY_PATTERNS = [
        r"(?i)\b(minor\s+defect|mislabel|cosmetic|class\s*iii\s*recall|precautionary)\b",
        r"(?i)\b(scheduled\s+maintenance|routine\s+inspection)\b",
    ]

    SOURCE_CREDIBILITY: Dict[str, float] = {
        "fda": 1.0,
        "cpsc": 1.0,
        "usda": 1.0,
        "fsis": 1.0,
        "cdc": 1.0,
        "epa": 0.95,
        "openfda": 1.0,
        "gov": 0.95,
        "official_rss": 0.9,
        "civic_notice": 0.85,
        "news": 0.75,
        "social": 0.50,
        "reddit": 0.50,
        "unknown": 0.40,
    }

    def assess_base_severity(self, text: str) -> float:
        """Determines baseline urgency from semantic severity markers."""
        if not text:
            return 10.0

        for pattern in self.HIGH_SEVERITY_PATTERNS:
            if re.search(pattern, text):
                return 88.0

        for pattern in self.MEDIUM_SEVERITY_PATTERNS:
            if re.search(pattern, text):
                return 65.0

        for pattern in self.LOW_SEVERITY_PATTERNS:
            if re.search(pattern, text):
                return 35.0

        return 45.0

    def get_source_credibility(self, source_name: str) -> float:
        """Determines credibility score (0.0 to 1.0) based on issuing domain/source."""
        source_lower = source_name.lower()
        for key, weight in self.SOURCE_CREDIBILITY.items():
            if key in source_lower:
                return weight
        return self.SOURCE_CREDIBILITY["unknown"]

    def calculate_recency_factor(self, published_at: Optional[str]) -> float:
        """Calculates decay factor between 0.6 and 1.0 based on age in days."""
        if not published_at:
            return 0.85
        try:
            # Handle ISO timestamp or simple date YYYY-MM-DD
            dt = None
            if "T" in published_at:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(published_at[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days = (now - dt).total_seconds() / 86400.0
            if days <= 1.0:
                return 1.0
            elif days <= 3.0:
                return 0.90
            elif days <= 7.0:
                return 0.75
            else:
                return 0.60
        except Exception:
            return 0.85

    def score(
        self,
        text: str,
        source: str = "unknown",
        published_at: Optional[str] = None,
        corroboration_count: int = 1,
        has_verified_batch: bool = False,
        ocr_confidence: Optional[float] = None,
    ) -> ScoringResult:
        """Combines content severity with non-LLM signals into final scores.

        Scoring formula:
        Final_Urgency = min(100.0,
            (Base_Severity * 0.55) +
            (Source_Credibility * 20.0) +
            (Recency_Factor * 10.0) +
            (Corroboration_Bonus) +
            (Batch_ID_Bonus)
        )
        """
        base_severity = self.assess_base_severity(text)
        credibility = self.get_source_credibility(source)
        recency = self.calculate_recency_factor(published_at)

        # Corroboration bonus: 2 sources = +8 pts, 3+ sources = +12 pts
        corroboration_bonus = 0.0
        if corroboration_count >= 3:
            corroboration_bonus = 12.0
        elif corroboration_count == 2:
            corroboration_bonus = 8.0

        batch_bonus = 5.0 if has_verified_batch else 0.0

        # Calculate combined urgency
        raw_urgency = (
            (base_severity * 0.55)
            + (credibility * 20.0)
            + (recency * 10.0)
            + corroboration_bonus
            + batch_bonus
        )
        final_urgency = round(min(100.0, max(0.0, raw_urgency)), 1)

        # Relevance score: 85+ if public recall/safety, adjusted by credibility and text length
        text_len = len(text.strip()) if text else 0
        relevance_base = 80.0 if base_severity > 40 else 50.0
        final_relevance = round(
            min(100.0, max(0.0, (relevance_base * 0.7) + (credibility * 20.0) + min(10.0, text_len / 50.0))),
            1,
        )

        uncertainty_flags = []
        if credibility <= 0.5:
            uncertainty_flags.append("unverified_source")
        if ocr_confidence is not None and ocr_confidence < 60.0:
            uncertainty_flags.append("low_ocr_confidence")
        if not has_verified_batch:
            uncertainty_flags.append("no_batch_id")

        return ScoringResult(
            relevance_score=final_relevance,
            urgency_score=final_urgency,
            llm_urgency=round(base_severity, 1),
            non_llm_urgency=round((credibility * 20.0) + (recency * 10.0) + corroboration_bonus + batch_bonus, 1),
            evidence_snippets=[text.strip()[:160]] if text else [],
            breakdown={
                "base_severity": round(base_severity, 1),
                "source_credibility_pts": round(credibility * 20.0, 1),
                "recency_pts": round(recency * 10.0, 1),
                "corroboration_bonus": corroboration_bonus,
                "batch_id_bonus": batch_bonus,
            },
            uncertainty_flags=uncertainty_flags,
        )

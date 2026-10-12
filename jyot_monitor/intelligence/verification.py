"""Claim verification and self-checking critique for high-urgency items."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from jyot_monitor.schemas import ItemSchema, ScoringResult


class UrgencyVerifier:
    """Independent verification and critique module for high-priority claims."""

    def __init__(self, urgency_threshold: float = 75.0):
        self.urgency_threshold = urgency_threshold

    def critique_claim(
        self,
        item: ItemSchema,
        current_scoring: ScoringResult,
        corroborating_items: List[ItemSchema],
    ) -> Tuple[bool, float, List[str], str]:
        """Critiques a high-urgency claim to prevent hallucinated or unverified alerts.

        Returns (is_verified, adjusted_urgency, verification_flags, explanation).
        """
        initial_urgency = current_scoring.urgency_score
        flags: List[str] = []
        explanation_parts: List[str] = []

        # 1. Source Trust Assessment
        src_lower = item.source.lower()
        is_official = any(o in src_lower for o in ["fda", "cpsc", "usda", "gov", "fsis"])

        # 2. Corroboration Check
        # Filter corroborating items from independent sources
        independent_sources = {
            c.source for c in corroborating_items if c.source != item.source
        }
        has_corroboration = len(independent_sources) > 0 or len(corroborating_items) >= 2

        if is_official:
            explanation_parts.append(f"Official regulator source '{item.source}' carries high inherent authority.")
            is_verified = True
        elif has_corroboration:
            sources_str = ", ".join(list(independent_sources)[:2])
            explanation_parts.append(
                f"Claim corroborated across {len(corroborating_items)} items from sources: {sources_str}."
            )
            is_verified = True
        else:
            is_verified = False
            flags.append("single_unverified_source")
            explanation_parts.append(
                f"Single uncorroborated source '{item.source}'. Downgrading urgency until second source confirms."
            )

        # 3. Check for vague or sensationalist wording without concrete identifiers
        text = item.text.lower()
        has_concrete_id = bool(
            re.search(r"\b(lot|batch|model|upc|recall\s*#|ndc)\b", text)
            or re.search(r"\b\d{4,}\b", text)
        )
        if not has_concrete_id and not is_official:
            flags.append("lacks_concrete_lot_or_model")
            explanation_parts.append("Lacks specific lot/serial number to confirm authentic safety advisory.")

        # 4. Urgency Adjustment
        adjusted_urgency = initial_urgency
        if not is_verified:
            # Downgrade unverified claims by 15 points
            adjusted_urgency = max(40.0, initial_urgency - 15.0)
            flags.append("urgency_downgraded_by_verifier")
        elif is_verified and has_corroboration:
            # Verified and corroborated
            adjusted_urgency = min(100.0, initial_urgency + 5.0)

        explanation = " ".join(explanation_parts)
        return is_verified, round(adjusted_urgency, 1), flags, explanation

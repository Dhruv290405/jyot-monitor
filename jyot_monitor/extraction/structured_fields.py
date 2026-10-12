"""Structured field extraction for public notices and recall bulletins."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from jyot_monitor.schemas import StructuredNotice


class StructuredFieldExtractor:
    """Extracts structured notice fields from plain or OCR-recovered text with uncertainty flags."""

    # Patterns for entity and field detection
    ORGANIZATION_PATTERNS = [
        r"(?i)\b(FDA|US\s*FDA|Food\s*and\s*Drug\s*Administration)\b",
        r"(?i)\b(CPSC|Consumer\s*Product\s*Safety\s*Commission)\b",
        r"(?i)\b(USDA|FSIS|Food\s*Safety\s*and\s*Inspection\s*Service)\b",
        r"(?i)\b(CDC|Centers\s*for\s*Disease\s*Control)\b",
        r"(?i)\b(EPA|Environmental\s*Protection\s*Agency)\b",
        r"(?i)\b(NHTSA|National\s*Highway\s*Traffic\s*Safety)\b",
        r"(?i)\b(City\s*of\s*[A-Z][a-z]+|Municipal\s*Corporation|Department\s*of\s*[A-Z][a-z]+)\b",
    ]

    NOTICE_TYPE_PATTERNS = [
        (r"(?i)\b(Class\s*I\s*Recall|Class\s*II\s*Recall|Voluntary\s*Recall|Product\s*Recall)\b", "Recall"),
        (r"(?i)\b(Safety\s*Advisory|Public\s*Health\s*Alert|Safety\s*Warning)\b", "Safety Advisory"),
        (r"(?i)\b(Boil\s*Water\s*Advisory|Water\s*Contamination)\b", "Civic Advisory"),
        (r"(?i)\b(Power\s*Outage|Grid\s*Failure|Service\s*Disruption)\b", "Outage Notice"),
        (r"(?i)\b(Evacuation\s*Order|Hazardous\s*Spill)\b", "Emergency Order"),
    ]

    BATCH_PATTERNS = [
        r"(?i)\b(?:lot|batch|serial|model|recall)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9\-]{4,20})\b",
        r"(?i)\bUPC\s*[:\-]?\s*(\d{10,14})\b",
    ]

    ACTION_PATTERNS = [
        r"(?i)\b(immediately\s+stop\s+using|do\s+not\s+consume|return\s+to\s+store|contact\s+for\s+refund|boil\s+water\s+before\s+use|seek\s+medical\s+attention)\b[^\.\n]*",
    ]

    def extract(self, text: str) -> StructuredNotice:
        """Extracts structured fields and documents uncertainty instead of guessing."""
        if not text or len(text.strip()) < 10:
            return StructuredNotice(
                uncertainty_flags=["insufficient_text", "empty_input"]
            )

        uncertainty_flags: List[str] = []

        # 1. Organization
        organization = None
        for pattern in self.ORGANIZATION_PATTERNS:
            m = re.search(pattern, text)
            if m:
                organization = m.group(0).strip()
                break
        if not organization:
            uncertainty_flags.append("organization_unidentified")

        # 2. Notice Type
        notice_type = None
        for pattern, label in self.NOTICE_TYPE_PATTERNS:
            if re.search(pattern, text):
                notice_type = label
                break
        if not notice_type:
            notice_type = "General Notice"
            uncertainty_flags.append("notice_type_inferred")

        # 3. Product / Subject
        product_or_subject = None
        # Look for phrases following 'recall of' or 'affecting'
        subject_match = re.search(r"(?i)\b(?:recall\s+of|recalls|affecting|concerning)\s+([A-Z0-9][A-Za-z0-9\s,\-'\"]{5,60})(?:\.|\n|due\s+to|because)", text)
        if subject_match:
            product_or_subject = subject_match.group(1).strip()
        else:
            uncertainty_flags.append("product_subject_uncertain")

        # 4. Batch / Reference Number
        batch_number = None
        for pattern in self.BATCH_PATTERNS:
            m = re.search(pattern, text)
            if m:
                batch_number = m.group(1).strip()
                break
        if not batch_number:
            uncertainty_flags.append("batch_number_missing")

        # 5. Date
        date_match = re.search(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b", text)
        date_str = date_match.group(0) if date_match else None
        if not date_str:
            uncertainty_flags.append("date_unspecified")

        # 6. Action Required
        action_required = None
        for pattern in self.ACTION_PATTERNS:
            m = re.search(pattern, text)
            if m:
                action_required = m.group(0).strip()
                break
        if not action_required:
            uncertainty_flags.append("action_required_unspecified")

        # 7. Supporting Evidence Snippet (First 180 chars of most relevant sentence)
        evidence_snippet = text.strip()[:200]

        return StructuredNotice(
            organization=organization,
            notice_type=notice_type,
            product_or_subject=product_or_subject,
            batch_or_reference_number=batch_number,
            date=date_str,
            location=None,
            action_required=action_required,
            supporting_evidence=evidence_snippet,
            uncertainty_flags=uncertainty_flags,
        )

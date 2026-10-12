"""PII detection and redaction for text and OCR-extracted content."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


class PIIRedactor:
    """Detects and redacts Personally Identifiable Information (PII) before storage/display."""

    PATTERNS: Dict[str, Tuple[re.Pattern, str]] = {
        "email": (
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
            "[EMAIL_REDACTED]",
        ),
        "phone": (
            re.compile(
                r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|"  # US/Intl format
                r"(?:\+?91[-.\s]?)?[6-9]\d{9}\b"  # Indian 10-digit mobile format
            ),
            "[PHONE_REDACTED]",
        ),
        "ssn": (
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
            "[SSN_REDACTED]",
        ),
        "aadhaar": (
            re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"),
            "[AADHAAR_REDACTED]",
        ),
        "credit_card": (
            re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
            "[CARD_REDACTED]",
        ),
        "api_key": (
            re.compile(r"\b(?:api[_-]?key|secret|token|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?", re.IGNORECASE),
            "[SECRET_REDACTED]",
        ),
    }

    def redact(self, text: str) -> Tuple[str, List[str]]:
        """Redacts PII from text.

        Returns (redacted_text, detected_pii_types).
        """
        if not text:
            return "", []

        redacted = text
        detected = []

        for pii_type, (regex, replacement) in self.PATTERNS.items():
            if regex.search(redacted):
                detected.append(pii_type)
                redacted = regex.sub(replacement, redacted)

        return redacted, detected

    def has_pii(self, text: str) -> bool:
        """Quick boolean check if text contains PII."""
        if not text:
            return False
        for regex, _ in self.PATTERNS.values():
            if regex.search(text):
                return True
        return False

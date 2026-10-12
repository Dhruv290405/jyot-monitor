"""Spam and coordinated post detection."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Tuple


class SpamDetector:
    """Detects low-quality, repetitive, or coordinated spam posts."""

    def __init__(self, min_length: int = 10, max_repetition_ratio: float = 0.5):
        self.min_length = min_length
        self.max_repetition_ratio = max_repetition_ratio

    def calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of characters in text."""
        if not text:
            return 0.0
        counts = Counter(text)
        total = len(text)
        return -sum((c / total) * math.log2(c / total) for c in counts.values())

    def check_repetition(self, text: str) -> float:
        """Check the fraction of repeated words in the text."""
        words = re.findall(r"\b\w+\b", text.lower())
        if not words:
            return 0.0
        unique_words = set(words)
        return 1.0 - (len(unique_words) / len(words))

    def evaluate(self, text: str) -> Tuple[bool, List[str]]:
        """Evaluates whether text is likely spam.

        Returns (is_spam, flags).
        """
        if not text or len(text.strip()) < self.min_length:
            return True, ["too_short"]

        flags = []
        cleaned = text.strip()

        # Check repetition ratio
        rep_ratio = self.check_repetition(cleaned)
        if len(cleaned.split()) >= 8 and rep_ratio > self.max_repetition_ratio:
            flags.append("excessive_word_repetition")

        # Check entropy (e.g. repeated single characters 'aaaaaaaa' or gibberish)
        entropy = self.calculate_entropy(cleaned)
        if len(cleaned) > 20 and entropy < 2.0:
            flags.append("low_entropy_repetitive_text")

        # Check link stuffing
        links = re.findall(r"https?://\S+", cleaned)
        if len(links) >= 3 and len(cleaned) < 200:
            flags.append("link_stuffing")

        # Check all caps scream spam
        alpha_chars = [c for c in cleaned if c.isalpha()]
        if len(alpha_chars) > 20:
            upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
            if upper_ratio > 0.85:
                flags.append("excessive_caps")

        return len(flags) > 0, flags

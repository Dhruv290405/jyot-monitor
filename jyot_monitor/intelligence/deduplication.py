"""Multimodal and cross-modal deduplication."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image
from rapidfuzz import fuzz
import imagehash


class MultimodalDeduplicator:
    """Detects duplicates across text, image hashes, and cross-modal text-vs-screenshot pairs."""

    def __init__(
        self,
        text_similarity_threshold: float = 85.0,
        phash_max_distance: int = 8,
    ):
        self.text_similarity_threshold = text_similarity_threshold
        self.phash_max_distance = phash_max_distance

    def normalize_text(self, text: str) -> str:
        """Normalizes text for fuzzy deduplication."""
        if not text:
            return ""
        # Lowercase, strip punctuation and extra whitespace
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        return " ".join(cleaned.split())

    def compute_image_phash(self, img_input: Union[str, Path, Image.Image]) -> Optional[str]:
        """Computes perceptual hash string for an image."""
        try:
            if isinstance(img_input, (str, Path)):
                img = Image.open(str(img_input)).convert("RGB")
            else:
                img = img_input
            return str(imagehash.phash(img))
        except Exception:
            return None

    def compare_texts(self, text_a: str, text_b: str) -> float:
        """Computes combined token sort and token set similarity between two texts (0.0 to 100.0)."""
        norm_a = self.normalize_text(text_a)
        norm_b = self.normalize_text(text_b)
        if not norm_a or not norm_b:
            return 0.0
        sort_ratio = float(fuzz.token_sort_ratio(norm_a, norm_b))
        set_ratio = float(fuzz.token_set_ratio(norm_a, norm_b))
        return max(sort_ratio, set_ratio)

    def compare_phashes(self, hash_a: str, hash_b: str) -> int:
        """Computes Hamming distance between two perceptual hash strings."""
        try:
            h_a = imagehash.hex_to_hash(hash_a)
            h_b = imagehash.hex_to_hash(hash_b)
            return int(h_a - h_b)
        except Exception:
            return 999

    def check_duplicate(
        self,
        text_a: str,
        text_b: str,
        ocr_text_a: Optional[str] = None,
        ocr_text_b: Optional[str] = None,
        phash_a: Optional[str] = None,
        phash_b: Optional[str] = None,
    ) -> Tuple[bool, str, float]:
        """Evaluates whether item A and item B are duplicates across modalities.

        Returns (is_duplicate, match_type, similarity_metric).
        """
        # 1. Image Perceptual Hash match
        if phash_a and phash_b:
            dist = self.compare_phashes(phash_a, phash_b)
            if dist <= self.phash_max_distance:
                sim = max(0.0, 100.0 - (dist * 10.0))
                return True, "image_phash", sim

        # 2. Text to Text match
        if text_a and text_b:
            text_sim = self.compare_texts(text_a, text_b)
            if text_sim >= self.text_similarity_threshold:
                return True, "text_fuzzy", text_sim

        # 3. Cross-Modal Match: OCR text from A vs Post text from B
        if ocr_text_a and text_b:
            cross_sim_1 = self.compare_texts(ocr_text_a, text_b)
            if cross_sim_1 >= self.text_similarity_threshold:
                return True, "cross_modal_ocr_a_vs_text_b", cross_sim_1

        # Cross-Modal Match: Post text from A vs OCR text from B
        if text_a and ocr_text_b:
            cross_sim_2 = self.compare_texts(text_a, ocr_text_b)
            if cross_sim_2 >= self.text_similarity_threshold:
                return True, "cross_modal_text_a_vs_ocr_b", cross_sim_2

        # 4. OCR text from A vs OCR text from B
        if ocr_text_a and ocr_text_b:
            ocr_sim = self.compare_texts(ocr_text_a, ocr_text_b)
            if ocr_sim >= self.text_similarity_threshold:
                return True, "ocr_text_fuzzy", ocr_sim

        return False, "none", 0.0

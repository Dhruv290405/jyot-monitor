"""Tesseract OCR engine integration with confidence normalization."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image
import pytesseract

from jyot_monitor.extraction.preprocess import ImagePreprocessor
from jyot_monitor.schemas import OCRExtractResult


class TesseractEngine:
    """Conventional OCR engine using Tesseract."""

    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        preprocessor: Optional[ImagePreprocessor] = None,
    ):
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.tesseract_cmd = tesseract_cmd or "tesseract"
        # Check if tesseract binary is available
        self.is_available = self._check_availability()
        if self.is_available and tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def _check_availability(self) -> bool:
        """Check if Tesseract binary is executable."""
        cmd = self.tesseract_cmd or "tesseract"
        resolved = shutil.which(cmd)
        if resolved:
            return True
        # Check standard Windows paths
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for p in common_paths:
            if Path(p).exists():
                self.tesseract_cmd = p
                pytesseract.pytesseract.tesseract_cmd = p
                return True
        return False

    def extract(
        self,
        image_input: Union[str, Path, bytes, Image.Image],
        language: str = "eng",
        profile: str = "standard",
        page_number: int = 1,
        total_pages: int = 1,
    ) -> OCRExtractResult:
        """Runs Tesseract OCR on the given image.

        Language can be 'eng', 'hin', or 'hin+eng'.
        """
        start_time = time.time()

        if not self.is_available:
            return OCRExtractResult(
                engine="tesseract",
                engine_version="unavailable",
                text="",
                confidence=0.0,
                raw_confidence=0.0,
                language=language,
                preprocessing_profile=profile,
                needs_second_opinion=True,
                router_decision="engine_fallback",
                router_rationale="Tesseract binary not found on host environment; falling back to alternative engine.",
                page_number=page_number,
                total_pages=total_pages,
                is_fallback=True,
                error="Tesseract executable not found in PATH or standard locations.",
                latency_seconds=time.time() - start_time,
            )

        try:
            # Apply preprocessing
            preprocessed_img = self.preprocessor.apply_profile(image_input, profile=profile)

            # Run OCR data extraction for word-level confidences and layout
            ocr_data = pytesseract.image_to_data(
                preprocessed_img,
                lang=language,
                output_type=pytesseract.Output.DICT,
            )

            # Calculate normalized confidence
            words: List[str] = []
            confidences: List[float] = []

            for i, word in enumerate(ocr_data.get("text", [])):
                word_clean = word.strip()
                if word_clean:
                    words.append(word_clean)
                    raw_conf = float(ocr_data["conf"][i])
                    if raw_conf >= 0:  # -1 represents non-word or spaces
                        confidences.append(raw_conf)

            full_text = " ".join(words)
            mean_conf = (
                sum(confidences) / len(confidences) if confidences else (50.0 if full_text else 0.0)
            )

            latency = time.time() - start_time
            needs_second_opinion = (mean_conf < 60.0 or len(full_text.strip()) == 0)

            return OCRExtractResult(
                engine="tesseract",
                engine_version="5.x",
                text=full_text,
                confidence=round(mean_conf, 2),
                raw_confidence=round(mean_conf, 2),
                language=language,
                preprocessing_profile=profile,
                needs_second_opinion=needs_second_opinion,
                router_decision="tesseract_executed",
                router_rationale=f"Executed Tesseract ({language}) with profile '{profile}'. Word count: {len(words)}.",
                page_number=page_number,
                total_pages=total_pages,
                layout_hints={
                    "word_count": len(words),
                    "line_count": len(set(ocr_data.get("line_num", []))),
                    "box_count": len(ocr_data.get("left", [])),
                },
                is_fallback=False,
                latency_seconds=round(latency, 3),
            )

        except Exception as e:
            latency = time.time() - start_time
            return OCRExtractResult(
                engine="tesseract",
                engine_version="5.x",
                text="",
                confidence=0.0,
                language=language,
                preprocessing_profile=profile,
                needs_second_opinion=True,
                router_decision="tesseract_error",
                router_rationale=f"Tesseract execution error: {str(e)}",
                page_number=page_number,
                total_pages=total_pages,
                is_fallback=True,
                error=str(e),
                latency_seconds=round(latency, 3),
            )

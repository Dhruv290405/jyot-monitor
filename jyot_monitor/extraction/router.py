"""Explicit multi-engine OCR router based on measurable image and document signals."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from PIL import Image

from jyot_monitor.extraction.preprocess import ImagePreprocessor
from jyot_monitor.extraction.tesseract_engine import TesseractEngine
from jyot_monitor.extraction.vision_engine import VisionEngine
from jyot_monitor.schemas import OCRExtractResult

logger = logging.getLogger(__name__)


class OCRRouter:
    """Evaluates measurable signals and routes visual extraction to the best engine."""

    def __init__(
        self,
        tesseract_engine: Optional[TesseractEngine] = None,
        vision_engine: Optional[VisionEngine] = None,
        preprocessor: Optional[ImagePreprocessor] = None,
        confidence_threshold: float = 60.0,
    ):
        self.preprocessor = preprocessor or ImagePreprocessor()
        self.tesseract = tesseract_engine or TesseractEngine(preprocessor=self.preprocessor)
        self.vision = vision_engine or VisionEngine()
        self.confidence_threshold = confidence_threshold

    def inspect_signals(
        self, image_input: Union[str, Path, bytes, Image.Image]
    ) -> Dict[str, Any]:
        """Calculates measurable image signals."""
        img = self.preprocessor.load_image(image_input)
        width, height = img.size
        pixel_count = width * height

        # Aspect ratio and resolution classification
        aspect_ratio = width / max(1, height)
        is_screenshot = (
            (width in (1080, 1170, 1284, 1290, 1440) or height in (1920, 2400, 2532, 2778, 2796))
            or (0.45 < aspect_ratio < 0.6)
            or (1.7 < aspect_ratio < 2.2)
        )
        is_low_res = (width < 400 or height < 400)
        is_very_large = pixel_count > 4_000_000

        return {
            "width": width,
            "height": height,
            "aspect_ratio": round(aspect_ratio, 2),
            "pixel_count": pixel_count,
            "is_screenshot": is_screenshot,
            "is_low_res": is_low_res,
            "is_very_large": is_very_large,
        }

    def route_and_extract(
        self,
        image_input: Union[str, Path, bytes, Image.Image],
        language_hint: Optional[str] = "en",
        page_number: int = 1,
        total_pages: int = 1,
        force_engine: Optional[str] = None,
    ) -> OCRExtractResult:
        """Determines best engine, logs rationale, and executes extraction with fallback."""
        signals = self.inspect_signals(image_input)

        # Determine language code for Tesseract
        lang_code = "eng"
        is_indic_script = False
        if language_hint and any(l in language_hint.lower() for l in ["hi", "hin", "hindi", "devanagari"]):
            lang_code = "hin+eng"
            is_indic_script = True

        # Choose profile based on signals
        if signals["is_low_res"]:
            profile = "upscale"
        elif signals["is_screenshot"]:
            profile = "crop_chrome"
        else:
            profile = "standard"

        # Explicit routing decision logic
        chosen_engine = "tesseract"
        rationale = ""

        if force_engine:
            chosen_engine = force_engine
            rationale = f"Engine forced by caller: {force_engine}"
        elif is_indic_script and not self.tesseract.is_available:
            chosen_engine = "vision_model"
            rationale = "Hindi script detected and Tesseract unavailable; routing to vision model."
        elif self.tesseract.is_available:
            chosen_engine = "tesseract"
            rationale = (
                f"Conventional OCR available. Fast path selected for {signals['width']}x{signals['height']} image "
                f"with profile '{profile}'."
            )
        else:
            chosen_engine = "vision_model"
            rationale = "Tesseract binary unavailable on host; routing to vision model engine."

        # Execute primary chosen engine
        if chosen_engine == "tesseract":
            result = self.tesseract.extract(
                image_input,
                language=lang_code,
                profile=profile,
                page_number=page_number,
                total_pages=total_pages,
            )
            result.router_decision = "tesseract_selected"
            result.router_rationale = rationale

            # Evaluate whether second opinion is required
            if result.needs_second_opinion or result.confidence < self.confidence_threshold:
                # Check if vision engine is available
                vis_avail, _ = self.vision.check_availability()
                if vis_avail:
                    sec_rationale = (
                        f"Tesseract confidence ({result.confidence}%) below threshold ({self.confidence_threshold}%). "
                        "Second opinion triggered via vision model."
                    )
                    vision_result = self.vision.extract_text(
                        image_input, page_number=page_number, total_pages=total_pages
                    )
                    vision_result.router_decision = "routed_second_opinion"
                    vision_result.router_rationale = sec_rationale
                    # If vision extracted meaningful text, prefer it
                    if len(vision_result.text.strip()) > len(result.text.strip()):
                        return vision_result

            return result

        else:
            # Vision model primary route
            result = self.vision.extract_text(
                image_input, page_number=page_number, total_pages=total_pages
            )
            result.router_decision = "vision_selected"
            result.router_rationale = rationale
            return result

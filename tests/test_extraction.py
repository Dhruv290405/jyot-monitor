"""Tests for visual extraction, preprocessing, PDF processing, and OCR routing."""

from pathlib import Path
from PIL import Image
import pytest

from jyot_monitor.extraction.preprocess import ImagePreprocessor
from jyot_monitor.extraction.pdf import PDFProcessor
from jyot_monitor.extraction.router import OCRRouter
from jyot_monitor.extraction.structured_fields import StructuredFieldExtractor


def test_image_preprocessing():
    prep = ImagePreprocessor()
    img = Image.new("RGB", (200, 200), color="white")

    # Standard
    p_std = prep.apply_profile(img, "standard")
    assert p_std.mode == "L"
    assert p_std.size == (200, 200)

    # Upscale
    p_up = prep.apply_profile(img, "upscale")
    assert p_up.size == (400, 400)

    # Binarize
    p_bin = prep.apply_profile(img, "binarize")
    assert p_bin.mode == "L"


def test_pdf_processing():
    pdf_processor = PDFProcessor()
    pdf_path = Path("data/sample_dataset/fda_food_safety_advisory.pdf")

    assert pdf_path.exists()
    total_pages, is_scanned = pdf_processor.inspect(pdf_path)
    assert total_pages == 2

    native_text = pdf_processor.extract_native_text(pdf_path)
    assert "CLASS I RECALL ADVISORY" in native_text

    rendered_img = pdf_processor.render_page(pdf_path, page_number=1)
    assert isinstance(rendered_img, Image.Image)
    assert rendered_img.width > 500


def test_router_signals():
    router = OCRRouter()
    img = Image.new("RGB", (1080, 2400), color="black")
    signals = router.inspect_signals(img)

    assert signals["is_screenshot"] is True
    assert signals["width"] == 1080
    assert signals["height"] == 2400


def test_structured_field_extractor():
    extractor = StructuredFieldExtractor()

    sample_text = (
        "U.S. FOOD AND DRUG ADMINISTRATION (FDA)\n"
        "Class I Recall of Organic Spinach due to Listeria.\n"
        "Lot number: LOT-2026-SP-9982. Date: Oct 2, 2026.\n"
        "Action: Immediately stop using and return to store."
    )

    notice = extractor.extract(sample_text)
    assert notice.organization is not None and any(k in notice.organization.upper() for k in ["FDA", "FOOD AND DRUG"])
    assert notice.notice_type == "Recall"
    assert notice.batch_or_reference_number == "LOT-2026-SP-9982"
    assert notice.action_required is not None
    assert len(notice.uncertainty_flags) == 0 or "product_subject_uncertain" in notice.uncertainty_flags

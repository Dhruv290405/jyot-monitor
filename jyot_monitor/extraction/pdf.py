"""PDF inspection, page rendering, and text extraction."""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Optional, Tuple, Union

import fitz  # PyMuPDF
from PIL import Image


class PDFProcessingError(Exception):
    """Raised when PDF loading or rendering fails."""
    pass


class PDFProcessor:
    """Handles multi-page PDF inspection, text extraction, and page rendering."""

    def __init__(self, dpi: int = 200):
        self.dpi = dpi
        self.zoom = dpi / 72.0  # 72 is standard PDF point resolution

    def inspect(self, pdf_path: Union[str, Path, bytes]) -> Tuple[int, bool]:
        """Inspects PDF and returns (total_pages, is_scanned_likely)."""
        try:
            if isinstance(pdf_path, bytes):
                doc = fitz.open(stream=pdf_path, filetype="pdf")
            else:
                doc = fitz.open(str(pdf_path))

            total_pages = len(doc)
            # Check if pages have native text
            total_text_length = 0
            for page in doc:
                total_text_length += len(page.get_text().strip())

            # If average text per page is less than 50 characters, it is likely scanned/image-only
            is_scanned = (total_text_length / max(1, total_pages)) < 50
            doc.close()
            return total_pages, is_scanned
        except Exception as e:
            raise PDFProcessingError(f"Failed to inspect PDF: {e}")

    def extract_native_text(self, pdf_path: Union[str, Path, bytes], max_pages: int = 10) -> str:
        """Extract native digital text if available."""
        try:
            if isinstance(pdf_path, bytes):
                doc = fitz.open(stream=pdf_path, filetype="pdf")
            else:
                doc = fitz.open(str(pdf_path))

            texts = []
            for i in range(min(len(doc), max_pages)):
                page_text = doc[i].get_text()
                if page_text.strip():
                    texts.append(f"--- Page {i+1} ---\n{page_text.strip()}")
            doc.close()
            return "\n\n".join(texts)
        except Exception as e:
            raise PDFProcessingError(f"Failed to extract native text: {e}")

    def render_page(
        self, pdf_path: Union[str, Path, bytes], page_number: int = 1
    ) -> Image.Image:
        """Render a specific PDF page (1-indexed) to a high-resolution PIL Image."""
        try:
            if isinstance(pdf_path, bytes):
                doc = fitz.open(stream=pdf_path, filetype="pdf")
            else:
                doc = fitz.open(str(pdf_path))

            if page_number < 1 or page_number > len(doc):
                doc.close()
                raise PDFProcessingError(
                    f"Page {page_number} out of bounds (1-{len(doc)})"
                )

            page = doc[page_number - 1]
            mat = fitz.Matrix(self.zoom, self.zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
            return img
        except Exception as e:
            raise PDFProcessingError(f"Failed to render page {page_number}: {e}")

    def render_all_pages(
        self, pdf_path: Union[str, Path, bytes], max_pages: int = 5
    ) -> List[Tuple[int, Image.Image]]:
        """Renders up to max_pages of a PDF to PIL Images."""
        pages = []
        total_pages, _ = self.inspect(pdf_path)
        for p in range(1, min(total_pages + 1, max_pages + 1)):
            img = self.render_page(pdf_path, page_number=p)
            pages.append((p, img))
        return pages

"""PDF text extraction helpers for the AI API."""

from __future__ import annotations

from io import BytesIO

import pdfplumber


MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_EXTRACTED_CHARACTERS = 80_000


class PDFExtractionError(ValueError):
    """Raised when an uploaded PDF cannot be safely extracted."""


def extract_pdf_text(contents: bytes) -> tuple[str, int, bool]:
    if not contents.startswith(b"%PDF-"):
        raise PDFExtractionError("The uploaded file is not a valid PDF.")
    if len(contents) > MAX_PDF_BYTES:
        raise PDFExtractionError("PDF files must be 15 MB or smaller.")

    try:
        with pdfplumber.open(BytesIO(contents)) as pdf:
            page_count = len(pdf.pages)
            if page_count > MAX_PDF_PAGES:
                raise PDFExtractionError("PDF files must contain 200 pages or fewer.")
            text = "\n\n".join(
                f"[Page {page.page_number}]\n{page.extract_text() or ''}"
                for page in pdf.pages
            ).strip()
    except PDFExtractionError:
        raise
    except Exception as error:
        raise PDFExtractionError("The PDF could not be read. It may be damaged or password-protected.") from error

    if not text:
        raise PDFExtractionError("No selectable text was found in this PDF. Scanned PDFs need OCR first.")

    truncated = len(text) > MAX_EXTRACTED_CHARACTERS
    return text[:MAX_EXTRACTED_CHARACTERS], page_count, truncated

"""PDF parser — text extraction + scanned PDF detection."""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 50  # Fewer chars than this means likely scanned


class PdfParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        text, tables, method = self._try_pymupdf(file_path)

        if not text or len(text.strip()) < MIN_TEXT_CHARS:
            # Try pdfplumber as secondary
            text2, tables2 = self._try_pdfplumber(file_path)
            if text2 and len(text2.strip()) >= MIN_TEXT_CHARS:
                text, tables, method = text2, tables2, "pdfplumber"
            else:
                # Scanned PDF — needs OCR
                return {
                    "raw_text": text or text2,
                    "raw_tables": None,
                    "ocr_required": True,
                    "confidence": 0.0,
                    "warnings": ["Scanned PDF detected — OCR required"],
                }

        return {
            "raw_text": text,
            "raw_tables": tables,
            "ocr_required": False,
            "confidence": 0.85,
            "warnings": [],
            "extraction_method": method,
        }

    def _try_pymupdf(self, file_path: str):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text_parts = []
            tables = []
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            return "\n".join(text_parts), tables, "pymupdf"
        except Exception as e:
            logger.warning(f"PyMuPDF failed: {e}")
            return None, None, "pymupdf"

    def _try_pdfplumber(self, file_path: str):
        try:
            import pdfplumber
            text_parts = []
            tables = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or "")
                    page_tables = page.extract_tables()
                    for t in (page_tables or []):
                        tables.append({"sheet": f"page_{page.page_number}", "rows": t})
            return "\n".join(text_parts), tables
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")
            return None, None

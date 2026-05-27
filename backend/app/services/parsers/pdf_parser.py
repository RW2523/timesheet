"""
PDF parser — 4-tier extraction chain.

Tier 1: Docling  (AI layout analysis, handles forms + tables + scanned)
Tier 2: pdfplumber (structured table extraction)
Tier 3: PyMuPDF  (text extraction fallback)
Tier 4: OCR flag (signals OCRService to run PaddleOCR/Tesseract)

OCR is triggered not just on text length but also on absence of date/time/hour patterns,
which catches PDFs that have garbled embedded text (common with scan + embed workflows).
"""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

# Date / time / hour patterns that indicate real timesheet content
_TIMESHEET_PATTERNS = re.compile(
    r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"   # dates: 04/01/2026
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*"  # month names
    r"|\d{1,2}:\d{2}"                           # times: 08:00
    r"|\bhours?\b|\bhrs?\b"                     # hour keywords
    r"|\b\d{4}-\d{2}-\d{2}\b",                 # ISO dates
    re.IGNORECASE,
)


class PdfParser:
    def parse(self, file_path: str) -> Dict[str, Any]:
        warnings: List[str] = []

        # --- Tier 1: Docling (best for complex layouts) ---
        docling_result = self._try_docling(file_path)
        if docling_result and self._is_sufficient(docling_result):
            return docling_result

        if docling_result:
            warnings.append("Docling low-quality result; trying pdfplumber")

        # --- Tier 2: pdfplumber (structured tables) ---
        text2, tables2, method2, pages2 = self._try_pdfplumber(file_path)
        if text2 and len(text2.strip()) >= settings.MIN_TEXT_CHARS_PDF and self._has_timesheet_content(text2):
            return {
                "raw_text": text2,
                "raw_tables": tables2 or [],
                "ocr_required": False,
                "confidence": 0.85,
                "warnings": warnings,
                "extraction_method": method2,
                "pages_count": pages2,
            }

        # Keep pdfplumber tables even if text is thin
        pdfplumber_tables = tables2 or []

        # --- Tier 3: PyMuPDF text ---
        text3, method3, pages3 = self._try_pymupdf(file_path)
        if text3 and len(text3.strip()) >= settings.MIN_TEXT_CHARS_PDF and self._has_timesheet_content(text3):
            return {
                "raw_text": text3,
                "raw_tables": pdfplumber_tables,
                "ocr_required": False,
                "confidence": 0.75,
                "warnings": warnings + ["Used PyMuPDF text fallback"],
                "extraction_method": method3,
                "pages_count": pages3,
            }

        # --- Tier 4: Scanned PDF → needs OCR ---
        # Return whatever text we have and flag for OCR
        total_pages = pages2 or pages3 or 0
        return {
            "raw_text": text2 or text3 or "",
            "raw_tables": pdfplumber_tables,
            "ocr_required": True,
            "confidence": 0.0,
            "warnings": warnings + ["Scanned/image PDF — OCR required"],
            "extraction_method": "ocr_pending",
            "pages_count": total_pages,
        }

    @staticmethod
    def _is_sufficient(result: Dict[str, Any]) -> bool:
        """Check if a result has enough data to proceed without OCR."""
        text = result.get("raw_text") or ""
        tables = result.get("raw_tables") or []
        has_tables = any(len(t.get("rows", [])) > 2 for t in tables)
        has_enough_text = len(text.strip()) >= settings.MIN_TEXT_CHARS_PDF
        has_content = has_tables or has_enough_text
        if not has_content:
            return False
        # Even if text is long enough, check it actually looks like a timesheet
        return PdfParser._has_timesheet_content(text) or has_tables

    @staticmethod
    def _has_timesheet_content(text: str) -> bool:
        """Return True if the text contains at least one date, time or hour-like pattern."""
        return bool(_TIMESHEET_PATTERNS.search(text or ""))

    def _try_docling(self, file_path: str) -> Optional[Dict[str, Any]]:
        try:
            from app.services.parsers.docling_parser import DoclingParser
            result = DoclingParser().parse(file_path)
            return result
        except Exception as e:
            logger.warning(f"Docling unavailable: {e}")
            return None

    def _try_pdfplumber(
        self, file_path: str
    ) -> Tuple[Optional[str], Optional[List], str, int]:
        try:
            import pdfplumber
            text_parts = []
            tables = []
            pages = 0
            with pdfplumber.open(file_path) as pdf:
                pages = len(pdf.pages)
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
                    page_tables = page.extract_tables() or []
                    for t in page_tables:
                        if t and len(t) > 1:
                            tables.append({"sheet": f"page_{page.page_number}", "rows": t})
            return "\n".join(text_parts), tables, "pdfplumber", pages
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")
            return None, None, "pdfplumber_failed", 0

    def _try_pymupdf(
        self, file_path: str
    ) -> Tuple[Optional[str], str, int]:
        try:
            import fitz
            doc = fitz.open(file_path)
            text_parts = []
            pages = len(doc)
            for page in doc:
                text_parts.append(page.get_text("text"))
            doc.close()
            return "\n".join(text_parts), "pymupdf", pages
        except Exception as e:
            logger.warning(f"PyMuPDF failed: {e}")
            return None, "pymupdf_failed", 0

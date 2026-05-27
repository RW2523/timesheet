"""
PDF Type Classifier.

Analyses a PDF file at the page level to determine:
  - text    : machine-readable text is directly embedded (use text parsers)
  - image   : pages are rasterised images / scanned (use OCR or VLM)
  - mixed   : combination of both (use both pipelines)
  - encrypted: password-protected, cannot read
  - unknown : very short / empty

Also emits an ordered list of recommended parsers based on the PDF type,
so callers can pick the right engine without guessing.
"""
from __future__ import annotations
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Minimum chars per page to call a page "text-based"
_MIN_TEXT_CHARS_PER_PAGE = 30


def classify_pdf(path: str) -> Dict[str, Any]:
    """
    Analyse a PDF file and return:
      type          : "text" | "image" | "mixed" | "encrypted" | "unknown"
      pages         : total page count
      text_pages    : pages with extractable text
      image_pages   : pages that appear to be scanned images
      avg_text_chars: average chars per page (text pages only)
      has_tables    : whether pdfplumber found any tables
      has_images    : whether embedded image objects were detected
      recommended_parsers: ordered list of recommended parsers
      notes         : human-readable explanation
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"error": "PyMuPDF not installed", "type": "unknown"}

    try:
        doc = fitz.open(path)
    except Exception as e:
        return {"error": str(e), "type": "unknown"}

    # Encrypted check
    if doc.is_encrypted:
        doc.close()
        return {
            "type": "encrypted",
            "pages": 0,
            "text_pages": 0,
            "image_pages": 0,
            "recommended_parsers": [],
            "notes": "PDF is password-protected. Cannot extract without the password.",
        }

    total_pages = len(doc)
    text_pages = 0
    image_pages = 0
    text_char_counts = []
    has_embedded_images = False
    page_details = []

    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        text_len = len(text.strip())
        images = page.get_images(full=False)
        has_image = len(images) > 0

        if has_image:
            has_embedded_images = True

        if text_len >= _MIN_TEXT_CHARS_PER_PAGE:
            text_pages += 1
            text_char_counts.append(text_len)
            page_type = "text"
        elif has_image:
            image_pages += 1
            page_type = "image"
        else:
            # Very sparse — could be blank or minimal vector graphics
            image_pages += 1
            page_type = "sparse"

        page_details.append({
            "page":      i + 1,
            "type":      page_type,
            "text_chars": text_len,
            "images":    len(images),
        })

    doc.close()

    avg_text = int(sum(text_char_counts) / len(text_char_counts)) if text_char_counts else 0

    # Check for tables with pdfplumber
    has_tables = False
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages[:5]:  # sample first 5 pages
                if pg.extract_tables():
                    has_tables = True
                    break
    except Exception:
        pass

    # Classify overall type
    if total_pages == 0:
        pdf_type = "unknown"
    elif text_pages == 0 and image_pages > 0:
        pdf_type = "image"
    elif image_pages == 0:
        pdf_type = "text"
    elif text_pages / total_pages >= 0.7:
        pdf_type = "text"   # mostly text
    elif image_pages / total_pages >= 0.7:
        pdf_type = "image"  # mostly scanned
    else:
        pdf_type = "mixed"

    recommended = _recommend_parsers(pdf_type, has_tables, avg_text)

    notes_map = {
        "text":  "Machine-readable text is embedded. Fast text parsers will work well.",
        "image": "Pages are scanned images. OCR and/or VLM required for extraction.",
        "mixed": "Some pages have text, others are images. Use both text parsers and OCR/VLM.",
        "unknown": "Could not determine PDF type — too short or empty.",
    }

    return {
        "type":                pdf_type,
        "pages":               total_pages,
        "text_pages":          text_pages,
        "image_pages":         image_pages,
        "avg_text_chars_pp":   avg_text,
        "has_tables":          has_tables,
        "has_embedded_images": has_embedded_images,
        "recommended_parsers": recommended,
        "page_details":        page_details[:20],  # cap to 20 pages for response size
        "notes":               notes_map.get(pdf_type, ""),
    }


def _recommend_parsers(pdf_type: str, has_tables: bool, avg_chars: int) -> List[Dict]:
    """Return ordered list of recommended parsers with explanation."""
    if pdf_type in ("image",):
        return [
            {"parser": "VLM",       "reason": "Vision LLM reads the page as an image — best for scanned/handwritten content",   "speed": "medium",  "quality": "high"},
            {"parser": "PaddleOCR", "reason": "GPU-accelerated OCR, very accurate on printed text",                               "speed": "fast",    "quality": "high"},
            {"parser": "Tesseract", "reason": "Classic OCR engine, solid fallback",                                               "speed": "medium",  "quality": "medium"},
            {"parser": "Docling",   "reason": "Layout-aware AI parser with built-in OCR",                                        "speed": "slow",    "quality": "high"},
        ]
    if pdf_type == "text" and has_tables:
        return [
            {"parser": "pdfplumber", "reason": "Best for table extraction in text PDFs",                                         "speed": "fast",    "quality": "high"},
            {"parser": "PyMuPDF",    "reason": "Fastest throughput for embedded text",                                           "speed": "fastest", "quality": "high"},
            {"parser": "pdfminer",   "reason": "Good layout-preserving text extraction",                                         "speed": "medium",  "quality": "medium"},
            {"parser": "Docling",    "reason": "AI-powered, excellent for complex tables",                                       "speed": "slow",    "quality": "highest"},
            {"parser": "marker",     "reason": "Research-paper quality layout reconstruction",                                   "speed": "slow",    "quality": "high"},
        ]
    if pdf_type == "text":
        return [
            {"parser": "PyMuPDF",    "reason": "Fastest text extraction, minimal overhead",                                      "speed": "fastest", "quality": "high"},
            {"parser": "pdfplumber", "reason": "More accurate than PyMuPDF for some layouts",                                    "speed": "fast",    "quality": "high"},
            {"parser": "pypdf",      "reason": "Minimal dependency pure-Python option",                                          "speed": "fast",    "quality": "medium"},
            {"parser": "pdfminer",   "reason": "Best for layout-preserving text output",                                         "speed": "medium",  "quality": "medium"},
            {"parser": "Docling",    "reason": "AI-powered, overkill for simple text PDFs but most thorough",                    "speed": "slow",    "quality": "highest"},
        ]
    # mixed
    return [
        {"parser": "Docling",    "reason": "Handles both text and image pages in one pass",                                      "speed": "slow",    "quality": "highest"},
        {"parser": "pdfplumber", "reason": "Good for text pages, extract tables",                                                "speed": "fast",    "quality": "high"},
        {"parser": "PyMuPDF",    "reason": "Fast text from text pages + convert image pages for OCR",                            "speed": "fastest", "quality": "high"},
        {"parser": "VLM",        "reason": "Process image pages with Vision LLM",                                                "speed": "medium",  "quality": "high"},
        {"parser": "PaddleOCR",  "reason": "OCR for scanned pages",                                                             "speed": "fast",    "quality": "high"},
    ]

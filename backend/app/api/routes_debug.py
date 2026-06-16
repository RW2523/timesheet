"""
Debug / Test Lab API — end-to-end pipeline visibility.

POST /debug/test-pipeline
  Accepts a single file upload, runs every pipeline stage independently,
  and returns ALL intermediate results so you can see exactly what each
  algorithm produced.

Pipeline stages (all run by default):
  1.  File Detection      — extension, MIME, size
  2.  PDF Classifier      — text vs image vs mixed vs encrypted (PDF only)
  3.  Multi-Parser        — all available PDF parsers side-by-side comparison
  4.  OCR                 — PaddleOCR + Tesseract (images & scanned PDFs)
  5.  VLM Vision          — Ollama vision model per-page extraction (images & scanned PDFs)
  6.  Docling             — AI-powered structured document parser
  7.  LLM Extraction      — Ollama / TRT-LLM text→structured JSON
  8.  Normalizer          — deterministic cleaning, dates, employee name
  9.  Employee Match      — fuzzy match against DB
  10. Validation Rules    — hours limits, missing data checks
"""
import os
import time
import logging
import tempfile
import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/debug")
logger = logging.getLogger(__name__)

MAX_TEST_FILE_MB = 50
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp"}


# ── Stage runner helpers ──────────────────────────────────────────────────────

def _stage(name: str, fn, *args, **kwargs) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        return {"stage": name, "status": "success",
                "duration_ms": round((time.perf_counter() - t0) * 1000),
                "output": result, "error": None}
    except Exception as e:
        logger.warning(f"[TestLab] Stage '{name}' error: {e}", exc_info=True)
        return {"stage": name, "status": "error",
                "duration_ms": round((time.perf_counter() - t0) * 1000),
                "output": None, "error": str(e)}


def _skipped(name: str, reason: str) -> Dict[str, Any]:
    return {"stage": name, "status": "skipped", "duration_ms": 0,
            "output": None, "error": reason}


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.post("/test-pipeline")
async def test_pipeline(
    file: UploadFile = File(...),
    run_ocr:      bool = Form(True),
    run_vlm:      bool = Form(True),
    run_docling:  bool = Form(True),
    run_llm:      bool = Form(True),
    run_match:    bool = Form(True),
    db: Session = Depends(get_db),
):
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_TEST_FILE_MB:
        raise HTTPException(413, f"File too large ({size_mb:.1f} MB). Max {MAX_TEST_FILE_MB} MB.")

    filename = file.filename or "test_file"
    ext = os.path.splitext(filename)[1].lower()

    tmp_dir  = tempfile.mkdtemp(prefix="testlab_")
    tmp_path = os.path.join(tmp_dir, filename)
    with open(tmp_path, "wb") as f:
        f.write(content)

    t_pipeline = time.perf_counter()
    stages: List[Dict[str, Any]] = []
    raw_text = ""

    try:
        # ── 1. File Detection ────────────────────────────────────────────────
        stages.append(_stage("File Detection", _detect_file, filename, ext, content, tmp_path))

        # ── 2. PDF Classifier (PDF only) ─────────────────────────────────────
        if ext == ".pdf":
            stages.append(_stage("PDF Classifier", _classify_pdf, tmp_path))
        else:
            stages.append(_skipped("PDF Classifier", f"Not a PDF (file is {ext})"))

        # ── 3. Multi-Parser Comparison (PDF only) ────────────────────────────
        multi_result = _skipped("Multi-Parser", "Not a PDF")
        if ext == ".pdf":
            multi_result = _stage("Multi-Parser", _run_all_pdf_parsers, tmp_path)
            if multi_result["status"] == "success" and multi_result["output"]:
                raw_text = multi_result["output"].get("best_text", "") or ""
        elif ext in (".xlsx", ".xls", ".csv", ".docx", ".doc"):
            multi_result = _stage("Multi-Parser", _run_office_parsers, ext, tmp_path)
            if multi_result["status"] == "success" and multi_result["output"]:
                raw_text = multi_result["output"].get("best_text", "") or ""
        stages.append(multi_result)

        # ── 4. OCR ───────────────────────────────────────────────────────────
        ocr_result = _skipped("OCR", "Disabled by request")
        if run_ocr:
            ocr_result = _stage("OCR", _run_ocr, ext, tmp_path)
            if ocr_result["status"] == "success" and ocr_result["output"]:
                ocr_text = ocr_result["output"].get("best_text", "") or ""
                if len(ocr_text) > len(raw_text):
                    raw_text = ocr_text
        stages.append(ocr_result)

        # ── 5. VLM Vision ────────────────────────────────────────────────────
        vlm_result = _skipped("VLM Vision", "Disabled by request")
        if run_vlm and (ext in IMAGE_EXTS or ext == ".pdf"):
            vlm_result = _stage("VLM Vision", _run_vlm, tmp_path, ext)
        elif run_vlm:
            vlm_result = _skipped("VLM Vision", f"VLM is for images/PDFs only (file is {ext})")
        stages.append(vlm_result)

        # ── 6. Docling ───────────────────────────────────────────────────────
        docling_result = _skipped("Docling", "Disabled by request")
        if run_docling and ext in {".pdf", ".docx", ".doc"} | IMAGE_EXTS:
            docling_result = _stage("Docling", _run_docling, tmp_path, ext)
            if docling_result["status"] == "success" and docling_result["output"]:
                dl_text = docling_result["output"].get("text", "") or ""
                if len(dl_text) > len(raw_text):
                    raw_text = dl_text
        elif run_docling:
            docling_result = _skipped("Docling", f"Not applicable for {ext} files")
        stages.append(docling_result)

        # ── 7. LLM Extraction ────────────────────────────────────────────────
        # Also absorb VLM entries into raw_text context
        llm_result = _skipped("LLM Extraction", "Disabled by request")
        if run_llm and raw_text.strip():
            llm_result = _stage("LLM Extraction", _run_llm, raw_text, filename)
        elif run_llm:
            llm_result = _skipped("LLM Extraction", "No text from any parser/OCR/Docling")
        stages.append(llm_result)

        # ── 8. Normalizer ────────────────────────────────────────────────────
        combined = _merge_all_sources(multi_result, llm_result, vlm_result)
        normalizer_result = _stage("Normalizer", _run_normalizer, combined, filename, raw_text)
        stages.append(normalizer_result)

        # ── 9. Employee Match ────────────────────────────────────────────────
        match_result = _skipped("Employee Match", "Disabled by request")
        if run_match:
            candidate = _extract_candidate_name(normalizer_result, llm_result, vlm_result, filename)
            match_result = _stage("Employee Match", _run_employee_match, candidate, db)
        stages.append(match_result)

        # ── 10. Validation Rules ─────────────────────────────────────────────
        entries = (normalizer_result.get("output") or {}).get("entries", [])
        stages.append(_stage("Validation Rules", _run_validation_rules, entries))

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    total_ms = round((time.perf_counter() - t_pipeline) * 1000)
    return {
        "file_name":    filename,
        "file_size_kb": round(size_mb * 1024, 1),
        "file_ext":     ext,
        "total_ms":     total_ms,
        "stages":       stages,
        "summary": {
            "text_chars_extracted": len(raw_text),
            "entries_found":        len(entries),
            "stages_ok":            sum(1 for s in stages if s["status"] == "success"),
            "stages_error":         sum(1 for s in stages if s["status"] == "error"),
            "stages_skipped":       sum(1 for s in stages if s["status"] == "skipped"),
        },
    }


# ── Stage 1: File Detection ───────────────────────────────────────────────────

def _detect_file(filename: str, ext: str, content: bytes, path: str) -> Dict:
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    size = len(content)
    return {
        "filename":        filename,
        "extension":       ext,
        "size_bytes":      size,
        "size_kb":         round(size / 1024, 1),
        "mime_type":       mime or "unknown",
        "is_image":        ext in IMAGE_EXTS,
        "is_pdf":          ext == ".pdf",
        "is_spreadsheet":  ext in {".xlsx", ".xls", ".csv"},
        "is_word":         ext in {".docx", ".doc"},
        "recommended_pipeline": (
            "PDF → classify → multi-parser → OCR/VLM if scanned → LLM" if ext == ".pdf"
            else "OCR + VLM → LLM" if ext in IMAGE_EXTS
            else "Direct parser → LLM"
        ),
    }


# ── Stage 2: PDF Classifier ───────────────────────────────────────────────────

def _classify_pdf(path: str) -> Dict:
    from app.services.pdf_classifier import classify_pdf
    return classify_pdf(path)


# ── Stage 3: Multi-Parser Comparison ─────────────────────────────────────────

def _run_all_pdf_parsers(path: str) -> Dict:
    """Run every available PDF parser and return side-by-side comparison."""
    results = {}

    # 1. PyMuPDF — fastest
    results["pymupdf"] = _parse_pymupdf(path)

    # 2. pdfplumber — best tables
    results["pdfplumber"] = _parse_pdfplumber(path)

    # 3. pypdf — minimal pure-Python
    results["pypdf"] = _parse_pypdf(path)

    # 4. pdfminer — layout-preserving
    results["pdfminer"] = _parse_pdfminer(path)

    # 5. marker — layout-aware AI (optional, heavy)
    results["marker"] = _parse_marker(path)

    # Pick the best (most chars)
    best_key = max(
        (k for k in results if not results[k].get("error")),
        key=lambda k: results[k].get("text_chars", 0),
        default=None,
    )

    return {
        "parsers":   results,
        "best_parser": best_key,
        "best_text": results[best_key]["text"][:3000] if best_key else "",
        "comparison": {
            k: {
                "text_chars": v.get("text_chars", 0),
                "tables":     v.get("tables", 0),
                "time_ms":    v.get("time_ms", 0),
                "error":      v.get("error"),
                "available":  not bool(v.get("error") and "not installed" in str(v.get("error", ""))),
            }
            for k, v in results.items()
        },
    }


def _parse_pymupdf(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        import fitz
        doc   = fitz.open(path)
        pages = len(doc)
        page_texts = []
        for i, pg in enumerate(doc):
            pt = pg.get_text("text") or ""
            page_texts.append(pt)
            logger.debug("pymupdf page %d/%d: %d chars", i + 1, pages, len(pt))
        text = "\n".join(page_texts)
        doc.close()
        logger.info("pymupdf: %d pages, %d total chars | first500: %s | last500: %s",
                    pages, len(text), repr(text[:500]), repr(text[-500:]))
        return {"text": text, "text_chars": len(text), "pages": pages,
                "tables": 0, "time_ms": round((time.perf_counter()-t0)*1000)}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0, "time_ms": round((time.perf_counter()-t0)*1000)}


def _parse_pdfplumber(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        import pdfplumber
        texts, tables_found = [], 0
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            for i, pg in enumerate(pdf.pages):
                pt = pg.extract_text() or ""
                texts.append(pt)
                tbls = pg.extract_tables() or []
                tables_found += len([t for t in tbls if t and len(t) > 1])
                logger.debug("pdfplumber page %d/%d: %d chars, %d tables", i+1, pages, len(pt), len(tbls))
        text = "\n".join(texts)
        logger.info("pdfplumber: %d pages, %d total chars | first500: %s | last500: %s",
                    pages, len(text), repr(text[:500]), repr(text[-500:]))
        return {"text": text, "text_chars": len(text), "tables": tables_found,
                "time_ms": round((time.perf_counter()-t0)*1000)}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0, "time_ms": round((time.perf_counter()-t0)*1000)}


def _parse_pypdf(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        pages  = len(reader.pages)
        page_texts = []
        for i, pg in enumerate(reader.pages):
            pt = pg.extract_text() or ""
            page_texts.append(pt)
            logger.debug("pypdf page %d/%d: %d chars", i+1, pages, len(pt))
        text = "\n".join(page_texts)
        logger.info("pypdf: %d pages, %d total chars | first500: %s | last500: %s",
                    pages, len(text), repr(text[:500]), repr(text[-500:]))
        return {"text": text, "text_chars": len(text),
                "pages": pages, "tables": 0,
                "time_ms": round((time.perf_counter()-t0)*1000)}
    except ImportError:
        return {"error": "pypdf not installed — run: pip install pypdf", "text": "", "text_chars": 0, "time_ms": 0}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0, "time_ms": round((time.perf_counter()-t0)*1000)}


def _parse_pdfminer(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        text = pdfminer_extract(path) or ""
        logger.info("pdfminer: %d total chars | first500: %s | last500: %s",
                    len(text), repr(text[:500]), repr(text[-500:]))
        return {"text": text, "text_chars": len(text), "tables": 0,
                "time_ms": round((time.perf_counter()-t0)*1000)}
    except ImportError:
        return {"error": "pdfminer.six not installed — run: pip install pdfminer.six", "text": "", "text_chars": 0, "time_ms": 0}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0, "time_ms": round((time.perf_counter()-t0)*1000)}


def _parse_marker(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        model_dict = create_model_dict()
        converter  = PdfConverter(artifact_dict=model_dict)
        rendered   = converter(path)

        # marker 1.10.x returns a RenderedDocument; .markdown is the full text
        if hasattr(rendered, "markdown"):
            text = rendered.markdown or ""
        elif hasattr(rendered, "text"):
            text = rendered.text or ""
        else:
            text = str(rendered)

        logger.info("marker: %d total chars | first500: %s | last500: %s",
                    len(text), repr(text[:500]), repr(text[-500:]))
        return {
            "text":       text,
            "text_chars": len(text),
            "tables":     0,
            "time_ms":    round((time.perf_counter() - t0) * 1000),
        }
    except ImportError:
        return {"error": "marker-pdf not installed — run: pip install marker-pdf",
                "text": "", "text_chars": 0, "time_ms": 0}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0,
                "time_ms": round((time.perf_counter() - t0) * 1000)}


def _run_office_parsers(ext: str, path: str) -> Dict:
    """Direct parse for non-PDF files (Excel, CSV, Word)."""
    t0 = time.perf_counter()
    results = {}

    if ext in (".xlsx", ".xls"):
        try:
            from app.services.parsers.excel_parser import ExcelParser
            r = ExcelParser().parse(path)
            results["excel_parser"] = {"text": (r.get("raw_text") or "")[:3000],
                                        "text_chars": len(r.get("raw_text") or ""),
                                        "tables": len(r.get("raw_tables") or []),
                                        "time_ms": round((time.perf_counter()-t0)*1000)}
        except Exception as e:
            results["excel_parser"] = {"error": str(e)}
    elif ext == ".csv":
        try:
            from app.services.parsers.csv_parser import CsvParser
            r = CsvParser().parse(path)
            results["csv_parser"] = {"text": (r.get("raw_text") or "")[:3000],
                                      "text_chars": len(r.get("raw_text") or ""),
                                      "tables": len(r.get("raw_tables") or []),
                                      "time_ms": round((time.perf_counter()-t0)*1000)}
        except Exception as e:
            results["csv_parser"] = {"error": str(e)}
    elif ext in (".docx", ".doc"):
        try:
            from app.services.parsers.docx_parser import DocxParser
            r = DocxParser().parse(path)
            results["docx_parser"] = {"text": (r.get("raw_text") or "")[:3000],
                                       "text_chars": len(r.get("raw_text") or ""),
                                       "tables": len(r.get("raw_tables") or []),
                                       "time_ms": round((time.perf_counter()-t0)*1000)}
        except Exception as e:
            results["docx_parser"] = {"error": str(e)}

    best_key = max((k for k in results if not results[k].get("error")),
                   key=lambda k: results[k].get("text_chars", 0), default=None)
    return {
        "parsers":     results,
        "best_parser": best_key,
        "best_text":   results[best_key]["text"] if best_key else "",
    }


# ── Stage 4: OCR ──────────────────────────────────────────────────────────────

def _run_tesseract(path: str, ext: str) -> Dict:
    """Run Tesseract OCR on all pages of a PDF or a single image."""
    try:
        import pytesseract
        from PIL import Image
        import fitz
        texts = []
        page_results = []
        if ext == ".pdf":
            doc   = fitz.open(path)
            pages = len(doc)
            logger.info("tesseract: processing all %d PDF pages", pages)
            for i in range(pages):
                pix = doc[i].get_pixmap(dpi=200)
                tmp = path + f"_tess_p{i}.png"
                pix.save(tmp)
                try:
                    pt = pytesseract.image_to_string(Image.open(tmp))
                    texts.append(pt)
                    page_results.append({"page": i+1, "chars": len(pt), "status": "success"})
                except Exception as pe:
                    page_results.append({"page": i+1, "error": str(pe), "status": "error"})
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                logger.debug("tesseract page %d/%d: %d chars", i+1, pages, len(texts[-1]) if texts else 0)
            doc.close()
            text = "\n\n--- PAGE BREAK ---\n\n".join(texts)
        else:
            text = pytesseract.image_to_string(Image.open(path))
            page_results = [{"page": 1, "chars": len(text), "status": "success"}]
        logger.info("tesseract: %d total chars | first500: %s | last500: %s",
                    len(text), repr(text[:500]), repr(text[-500:]))
        return {
            "text":         text,
            "text_chars":   len(text),
            "page_results": page_results,
            "engine":       "tesseract",
        }
    except Exception as e:
        logger.exception("tesseract failed")
        return {"error": str(e), "text": "", "text_chars": 0, "engine": "tesseract"}


def _run_paddleocr(path: str, ext: str) -> Dict:
    """Run PaddleOCR on all pages of a PDF or a single image."""
    try:
        from paddleocr import PaddleOCR
        from app.core.config import settings
        import fitz

        # PaddleOCR downloads models on first run — init with timeout handling
        logger.info("paddleocr: initialising (may download models on first run)")
        ocr = PaddleOCR(
            use_angle_cls=True, lang="en",
            use_gpu=settings.OCR_USE_GPU, show_log=False,
        )

        all_lines: list = []
        page_results: list = []

        if ext == ".pdf":
            doc   = fitz.open(path)
            pages = len(doc)
            logger.info("paddleocr: processing all %d PDF pages", pages)
            for i in range(pages):
                pix = doc[i].get_pixmap(dpi=200)
                tmp = path + f"_paddle_p{i}.png"
                pix.save(tmp)
                try:
                    data = ocr.ocr(tmp, cls=True)
                    if data and data[0]:
                        lines = [item[1][0] for item in data[0] if item and len(item) >= 2]
                        all_lines.extend(lines)
                        page_results.append({"page": i+1, "lines": len(lines), "status": "success"})
                    else:
                        page_results.append({"page": i+1, "lines": 0, "status": "empty"})
                except Exception as pe:
                    page_results.append({"page": i+1, "error": str(pe), "status": "error"})
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                logger.debug("paddleocr page %d/%d done", i+1, pages)
            doc.close()
            text = "\n".join(all_lines)
        else:
            data = ocr.ocr(path, cls=True)
            lines = []
            if data and data[0]:
                lines = [item[1][0] for item in data[0] if item and len(item) >= 2]
            text = "\n".join(lines)
            page_results = [{"page": 1, "lines": len(lines), "status": "success"}]

        logger.info("paddleocr: %d total chars | first500: %s | last500: %s",
                    len(text), repr(text[:500]), repr(text[-500:]))
        return {
            "text":         text,
            "text_chars":   len(text),
            "lines":        len(text.splitlines()),
            "page_results": page_results,
            "engine":       "paddleocr",
        }
    except Exception as e:
        logger.exception("paddleocr failed")
        return {"error": str(e), "text": "", "text_chars": 0, "engine": "paddleocr"}


def _run_ocr(ext: str, path: str) -> Dict:
    """Run both OCR engines and return combined result (used by DOCX paths)."""
    tess   = _run_tesseract(path, ext)
    paddle = _run_paddleocr(path, ext)
    best_text = tess["text"] if len(tess.get("text","")) >= len(paddle.get("text","")) else paddle["text"]
    return {
        "engines":   {"tesseract": tess, "paddle_ocr": paddle},
        "best_text": best_text,
        "text":      best_text,
    }


# ── Stage 5: VLM Vision ───────────────────────────────────────────────────────

def _run_vlm(path: str, ext: str) -> Dict:
    from app.services.vlm_service import VLMService
    svc = VLMService()
    if ext in IMAGE_EXTS:
        return svc.read_text_from_image(path, ext)
    elif ext == ".pdf":
        import fitz
        try:
            total_pages = len(fitz.open(path))
        except Exception:
            total_pages = "?"
        logger.info("vlm: PDF has %s pages — processing all (up to 20)", total_pages)
        return svc.read_text_from_pdf(path, max_pages=20)
    return {"error": f"VLM not applicable for {ext}", "raw_text": "", "page_results": []}


# ── Stage 5b: OCR + VLM Fusion ────────────────────────────────────────────────

def _run_ocr_vlm(path: str, ext: str) -> Dict:
    """OCR (accurate text) + VLM (layout) fusion → structured Markdown + tables."""
    from app.services.ocr_vlm_fusion_service import OcrVlmFusionService
    r = OcrVlmFusionService().process(path, ext, max_pages=20)
    if r.get("error") and not r.get("raw_text"):
        raise Exception(r["error"])

    raw_text   = r.get("raw_text") or ""
    raw_tables = r.get("raw_tables") or []
    page_results = r.get("page_results") or []

    summary_lines = []
    if r.get("model"):
        summary_lines.append(f"Vision model: {r['model']}")
    if r.get("pages_processed"):
        summary_lines.append(f"Pages processed: {r['pages_processed']}")
    for pg in page_results:
        if pg.get("status") == "success":
            summary_lines.append(
                f"  Page {pg['page']}: OCR {pg.get('ocr_chars',0)} chars "
                f"({pg.get('ocr_engine','?')}, conf {pg.get('ocr_confidence',0)}) "
                f"→ fused {pg.get('fused_chars',0)} chars"
            )
        else:
            summary_lines.append(f"  Page {pg['page']}: {pg.get('error','error')}")

    return {
        "text":          raw_text,
        "text_chars":    len(raw_text),
        "tables":        len(raw_tables),
        "raw_tables":    raw_tables,
        "ocr_text":      r.get("ocr_text", ""),
        "page_results":  page_results,
        "pages_processed": r.get("pages_processed", 0),
        "model":         r.get("model"),
        "warnings":      r.get("warnings", []),
        "fusion_summary": "\n".join(summary_lines),
        "raw_output":    r,
    }


# ── Stage 6: Docling ──────────────────────────────────────────────────────────

def _run_docling(path: str, ext: str) -> Dict:
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions

        # Use Tesseract CLI OCR — always available (tesseract binary is installed in container)
        # This avoids the missing RapidOCR/tesserocr model files at /storage/docling_models/
        ocr_options   = TesseractCliOcrOptions()
        pipeline_opts = PdfPipelineOptions(ocr_options=ocr_options)

        converter = DocumentConverter(
            format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_opts)}
        )
        result  = converter.convert(path)
        doc     = result.document
        md_text = doc.export_to_markdown() if hasattr(doc, "export_to_markdown") else str(doc)
        tables  = getattr(doc, "tables", []) or []
        logger.info("docling: %d total chars, %d tables | first500: %s | last500: %s",
                    len(md_text), len(tables), repr(md_text[:500]), repr(md_text[-500:]))
        return {
            "text":           md_text,
            "text_chars":     len(md_text),
            "tables_found":   len(tables),
            "tables_preview": [str(t)[:300] for t in tables[:2]],
            "ocr_backend":    "tesseract-cli",
        }
    except Exception as e:
        raise


# ── Stage 7: LLM Extraction ───────────────────────────────────────────────────

def _run_llm(raw_text: str, filename: str) -> Dict:
    from app.services.llm_service import LLMService, EXTRACTION_PROMPT_TEMPLATE
    from app.core.config import settings

    if not settings.LLM_ENABLED:
        return {"note": "LLM_ENABLED=false", "entries": []}

    svc = LLMService()

    # Prompt preview
    if "{raw_text}" in EXTRACTION_PROMPT_TEMPLATE:
        try:
            preview = EXTRACTION_PROMPT_TEMPLATE.format(raw_text=raw_text[:2000])
        except Exception:
            preview = raw_text[:500]
    else:
        preview = raw_text[:500]

    extracted = svc.extract_timesheet_json(raw_text=raw_text, file_metadata={"filename": filename})

    entries = []
    if isinstance(extracted, dict):
        entries = extracted.get("entries", [])
    elif isinstance(extracted, list):
        entries = extracted

    return {
        "provider":       settings.LLM_PROVIDER,
        "model":          getattr(settings, "OLLAMA_MODEL", "unknown"),
        "prompt_preview": preview[:1000] + ("…" if len(preview) > 1000 else ""),
        "entries_found":  len(entries),
        "entries":        entries,
        "employee_name":  (extracted or {}).get("employee_name") if isinstance(extracted, dict) else None,
    }


# ── Stage 8: Normalizer ───────────────────────────────────────────────────────

def _run_normalizer(combined_data: Dict, filename: str, raw_text: str) -> Dict:
    import re
    entries       = combined_data.get("entries", [])
    employee_name = combined_data.get("employee_name", "")

    if not employee_name:
        stem = os.path.splitext(filename)[0]
        stem = re.sub(r"\d{4}[-_]\d{2}[-_]\d{2}", "", stem)
        stem = re.sub(r"(?i)(timesheet|ts|hours|report|weekly|monthly)", "", stem)
        stem = re.sub(r"[-_]+", " ", stem).strip()
        if 3 < len(stem) < 40:
            employee_name = stem.title()

    dates = []
    total_hours = 0.0
    for e in entries:
        d = e.get("date") or e.get("work_date") or e.get("Date")
        if d:
            dates.append(str(d))
        for hk in ("hours", "regular_hours", "total_hours", "Hours"):
            v = e.get(hk)
            if v is not None:
                try:
                    total_hours += float(v); break
                except (TypeError, ValueError):
                    pass

    return {
        "employee_name_detected": employee_name,
        "entries_count":          len(entries),
        "entries":                entries[:20],
        "entries_truncated":      len(entries) > 20,
        "date_range":             f"{min(dates)} → {max(dates)}" if dates else "no dates found",
        "total_hours":            round(total_hours, 2),
        "unique_dates":           len(set(dates)),
    }


# ── Stage 9: Employee Match ───────────────────────────────────────────────────

def _run_employee_match(candidate_name: Optional[str], db: Session) -> Dict:
    from app.db.models import Employee
    from app.services.employee_match_service import EmployeeMatchService, _clean_name_for_matching

    all_employees = db.query(Employee).filter(Employee.is_active == True).all()
    total_in_db = len(all_employees)

    if not candidate_name:
        return {"candidate_name": None, "note": "No employee name detected", "employees_in_db": total_in_db, "match": None}

    cleaned = _clean_name_for_matching(candidate_name)
    try:
        svc = EmployeeMatchService(db)
        emp_id, confidence, method, alts = svc._find_match(cleaned)
        matched = None
        if emp_id:
            e = db.query(Employee).filter(Employee.id == emp_id).first()
            matched = {"id": emp_id, "full_name": e.full_name if e else "?", "email": e.email if e else "?"}
    except Exception as ex:
        return {"candidate_name": candidate_name, "error": str(ex), "employees_in_db": total_in_db}

    from app.core.config import settings
    return {
        "candidate_name":   candidate_name,
        "cleaned_name":     cleaned,
        "employees_in_db":  total_in_db,
        "matched_employee": matched,
        "confidence":       round(float(confidence), 3) if confidence else 0,
        "match_method":     method,
        "auto_threshold":   settings.FUZZY_AUTO_THRESHOLD,
        "review_threshold": settings.FUZZY_REVIEW_THRESHOLD,
        "would_auto_match": confidence >= settings.FUZZY_AUTO_THRESHOLD if confidence else False,
        "alternatives":     alts[:3] if alts else [],
    }


# ── Stage 10: Validation Rules ────────────────────────────────────────────────

def _run_validation_rules(entries: List[Dict]) -> Dict:
    from app.core.config import settings

    if not entries:
        return {"note": "No entries to validate", "issues": []}

    max_daily  = float(getattr(settings, "MAX_DAILY_HOURS", 12))
    max_weekly = float(getattr(settings, "REGULAR_WEEKLY_LIMIT_HOURS", 40))

    by_date: Dict[str, float] = {}
    for e in entries:
        d = str(e.get("date") or e.get("work_date") or "unknown")
        h = 0.0
        for k in ("hours", "regular_hours", "total_hours"):
            try:
                h = float(e.get(k) or 0)
                if h: break
            except (TypeError, ValueError):
                pass
        by_date[d] = by_date.get(d, 0) + h

    issues = []
    for d, h in by_date.items():
        if h > max_daily:
            issues.append({"rule": "DAILY_HOURS_EXCEED", "date": d, "hours": h, "limit": max_daily})
        if h == 0:
            issues.append({"rule": "ZERO_HOURS_DAY", "date": d})

    total = sum(by_date.values())
    if total > max_weekly * 2:
        issues.append({"rule": "WEEKLY_HOURS_EXCEED", "total": total, "limit": max_weekly})

    missing = sum(1 for e in entries if not any(e.get(k) for k in ("hours", "regular_hours", "total_hours")))
    if missing:
        issues.append({"rule": "MISSING_HOURS", "count": missing, "of": len(entries)})

    return {
        "entries_checked": len(entries),
        "daily_summary":   dict(sorted(by_date.items())),
        "total_hours":     round(total, 2),
        "issues_found":    len(issues),
        "issues":          issues,
        "max_daily_hours": max_daily,
        "max_weekly_hours": max_weekly,
    }


# ── Source merging ────────────────────────────────────────────────────────────

def _merge_all_sources(multi: Dict, llm: Dict, vlm: Dict) -> Dict:
    entries = []
    employee_name = ""

    # LLM entries take priority
    if llm["status"] == "success" and llm["output"]:
        entries.extend(llm["output"].get("entries", []))
        employee_name = llm["output"].get("employee_name", "") or employee_name

    # VLM entries supplement
    if vlm["status"] == "success" and vlm["output"]:
        vlm_entries = vlm["output"].get("entries", [])
        entries.extend(vlm_entries)
        if not employee_name:
            employee_name = vlm["output"].get("employee_name", "") or ""

    # Parser table rows as fallback
    if not entries and multi["status"] == "success" and multi["output"]:
        for parser_data in (multi["output"].get("parsers") or {}).values():
            if not parser_data.get("error") and parser_data.get("text_chars", 0) > 0:
                break

    return {"entries": entries, "employee_name": employee_name}


def _extract_candidate_name(
    norm: Dict, llm: Dict, vlm: Dict, filename: str
) -> Optional[str]:
    if norm["status"] == "success" and norm["output"]:
        n = norm["output"].get("employee_name_detected")
        if n: return n
    if llm["status"] == "success" and llm["output"]:
        n = llm["output"].get("employee_name")
        if n: return n
        for e in (llm["output"].get("entries") or []):
            if e.get("employee_name"): return e["employee_name"]
    if vlm["status"] == "success" and vlm["output"]:
        n = vlm["output"].get("employee_name")
        if n: return n
    stem = os.path.splitext(filename)[0]
    import re
    stem = re.sub(r"[-_\d]+", " ", stem).strip()
    return stem.title() if 4 < len(stem) < 40 else None


# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE TEST LAB — Session-based 3-step API
# ═══════════════════════════════════════════════════════════════════════════════
#
# Step 1  POST /debug/lab/upload                  → { session_id, file_info, pdf_classification }
# Step 2  POST /debug/lab/{sid}/run-parser        → { parser, text, text_chars, tables, raw_output }
# Step 3  POST /debug/lab/{sid}/run-llm           → { entries, summary, prompt_preview }
#         GET  /debug/lab/{sid}/info              → session metadata + available parsers
# ═══════════════════════════════════════════════════════════════════════════════

import uuid as _uuid

# In-memory session registry  { session_id → {path, filename, ext, size_kb, created_at} }
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSION_DIR = "/tmp/testlab_sessions"
os.makedirs(_SESSION_DIR, exist_ok=True)


def _get_session(sid: str) -> Dict[str, Any]:
    s = _SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, f"Session '{sid}' not found or expired. Upload a file first.")
    if not os.path.exists(s["path"]):
        raise HTTPException(410, "Session file has been cleaned up. Please re-upload.")
    return s


# ── Step 1: Upload ─────────────────────────────────────────────────────────────

@router.post("/lab/upload")
async def lab_upload(file: UploadFile = File(...)):
    """Upload a file once and receive a session_id. Use session_id for all subsequent calls."""
    content = await file.read()
    if len(content) > MAX_TEST_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large. Max {MAX_TEST_FILE_MB} MB.")

    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    sid = str(_uuid.uuid4())

    dest_dir  = os.path.join(_SESSION_DIR, sid)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)
    with open(dest_path, "wb") as fh:
        fh.write(content)

    _SESSIONS[sid] = {"session_id": sid, "path": dest_path,
                      "filename": filename, "ext": ext,
                      "size_kb": round(len(content)/1024, 1),
                      "created_at": time.time()}

    # Auto-classify PDF immediately (fast)
    pdf_info = None
    if ext == ".pdf":
        try:
            from app.services.pdf_classifier import classify_pdf
            pdf_info = classify_pdf(dest_path)
        except Exception:
            pass

    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    return {
        "session_id": sid,
        "file_info": {
            "filename": filename, "ext": ext,
            "size_kb": round(len(content)/1024, 1),
            "mime_type": mime or "unknown",
            "is_pdf": ext == ".pdf",
            "is_image": ext in IMAGE_EXTS,
        },
        "pdf_classification": pdf_info,
        "available_parsers": _get_available_parsers(ext),
    }


def _get_available_parsers(ext: str) -> List[Dict]:
    if ext == ".pdf":
        return [
            {"id": "pymupdf",    "name": "PyMuPDF",    "desc": "Fastest — direct text extraction",             "category": "text"},
            {"id": "pdfplumber", "name": "pdfplumber",  "desc": "Best table extraction quality",                "category": "text"},
            {"id": "pypdf",      "name": "pypdf",       "desc": "Pure-Python, minimal dependencies",            "category": "text"},
            {"id": "pdfminer",   "name": "pdfminer",    "desc": "Layout-preserving text extraction",            "category": "text"},
            {"id": "docling",    "name": "Docling",     "desc": "AI-powered — handles forms, tables, layouts",  "category": "ai"},
            {"id": "marker",     "name": "marker-pdf",  "desc": "Research-paper quality layout reconstruction", "category": "ai"},
            {"id": "tesseract",  "name": "Tesseract",   "desc": "Classic OCR — for scanned PDFs",              "category": "ocr"},
            {"id": "paddle",     "name": "PaddleOCR",   "desc": "GPU-accelerated OCR — high accuracy",         "category": "ocr"},
            {"id": "vlm",        "name": "VLM Vision",  "desc": "Vision LLM reads each page as image",         "category": "vlm"},
            {"id": "ocr_vlm",    "name": "OCR + VLM Fusion", "desc": "OCR text + VLM layout → structured tables (best for image PDFs)", "category": "vlm"},
        ]
    if ext in IMAGE_EXTS:
        return [
            {"id": "tesseract", "name": "Tesseract",  "desc": "Classic OCR engine",             "category": "ocr"},
            {"id": "paddle",    "name": "PaddleOCR",  "desc": "GPU-accelerated, high accuracy", "category": "ocr"},
            {"id": "vlm",       "name": "VLM Vision", "desc": "Vision LLM understands context", "category": "vlm"},
            {"id": "ocr_vlm",   "name": "OCR + VLM Fusion", "desc": "OCR text + VLM layout → structured tables", "category": "vlm"},
            {"id": "docling",   "name": "Docling",    "desc": "AI document parser",             "category": "ai"},
        ]
    if ext in (".xlsx", ".xls"):
        return [{"id": "excel", "name": "Excel Parser", "desc": "Pandas + openpyxl — all sheets and tables", "category": "text"}]
    if ext == ".csv":
        return [{"id": "csv", "name": "CSV Parser", "desc": "Smart CSV → structured tables", "category": "text"}]
    if ext in (".docx", ".doc"):
        return [
            {"id": "docx",     "name": "DOCX Parser",    "desc": "python-docx — paragraphs + tables",                    "category": "text"},
            {"id": "docling",  "name": "Docling",         "desc": "AI-powered document parser",                           "category": "ai"},
            {"id": "docx_ocr", "name": "DOCX Image OCR", "desc": "Extract embedded images → Tesseract + PaddleOCR",       "category": "ocr"},
            {"id": "docx_vlm", "name": "DOCX VLM",       "desc": "Extract embedded images → Vision LLM → rule-parser",   "category": "vlm"},
        ]
    return [{"id": "raw", "name": "Raw Text", "desc": "Read as plain text", "category": "text"}]


# ── Step 2: Run a single parser ────────────────────────────────────────────────

@router.post("/lab/{session_id}/run-parser")
async def lab_run_parser(session_id: str, body: dict):
    """Run one parser. Body: { "parser": "pymupdf" | "pdfplumber" | ... }

    For slow parsers (VLM, Docling, marker) the work runs in a thread pool so
    the async event loop is never blocked.  A StreamingResponse sends JSON
    chunks with periodic newline keep-alives so the Next.js proxy and browser
    never see a stale connection.
    """
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse as _SR

    s      = _get_session(session_id)
    parser = (body.get("parser") or "").lower().strip()
    if not parser:
        raise HTTPException(400, "Field 'parser' is required.")

    # For fast parsers just run synchronously in-thread and return immediately
    SLOW_PARSERS = {"vlm", "ocr_vlm", "docling", "marker", "docx_vlm", "docx_ocr", "tesseract", "paddle"}

    if parser not in SLOW_PARSERS:
        t0 = time.perf_counter()
        try:
            result = _dispatch_parser(parser, s["path"], s["ext"])
            return {"session_id": session_id, "parser": parser, "status": "success",
                    "duration_ms": round((time.perf_counter()-t0)*1000), **result}
        except HTTPException:
            raise
        except Exception as e:
            return {"session_id": session_id, "parser": parser, "status": "error",
                    "duration_ms": round((time.perf_counter()-t0)*1000),
                    "error": str(e), "text": "", "text_chars": 0}

    # Slow parsers: stream keepalive newlines while work runs in thread pool
    async def _stream():
        t0 = time.perf_counter()
        loop = asyncio.get_running_loop()

        # Run the blocking parser in a thread
        future = loop.run_in_executor(None, _dispatch_parser, parser, s["path"], s["ext"])

        # Send a keep-alive newline every 5 seconds until the parser finishes
        while not future.done():
            try:
                await asyncio.wait_for(asyncio.shield(future), timeout=5.0)
            except asyncio.TimeoutError:
                yield b"\n"   # keep-alive ping to prevent connection reset
            except Exception:
                break

        # Collect the result
        try:
            result = await future
            payload = {"session_id": session_id, "parser": parser, "status": "success",
                       "duration_ms": round((time.perf_counter()-t0)*1000), **result}
        except Exception as e:
            payload = {"session_id": session_id, "parser": parser, "status": "error",
                       "duration_ms": round((time.perf_counter()-t0)*1000),
                       "error": str(e), "text": "", "text_chars": 0}

        yield _json.dumps(payload).encode()

    return _SR(_stream(), media_type="application/json")


def _dispatch_docx_image_parser(path: str, mode: str) -> Dict[str, Any]:
    """Extract embedded images from a DOCX and run OCR or VLM on each one.

    mode = "docx_ocr"  → Tesseract + PaddleOCR per image, combine text
    mode = "docx_vlm"  → VLMService OCR prompt per image, then TimesheetRuleParser
    """
    import shutil, tempfile, time
    from app.services.parsers.docx_parser import DocxParser

    t0       = time.perf_counter()
    tmp_dir  = tempfile.mkdtemp(prefix="docx_imgs_")
    try:
        img_paths = DocxParser.extract_embedded_images(path, dest_dir=tmp_dir)
        if not img_paths:
            return {
                "text":       "",
                "text_chars": 0,
                "tables":     0,
                "images_found": 0,
                "error":      "No embedded images found in this DOCX file. "
                              "The document may be text-only — try the DOCX Parser instead.",
            }

        page_results: List[Dict] = []
        all_text_parts: List[str] = []

        if mode == "docx_ocr":
            # ── Tesseract + PaddleOCR on each image ───────────────────────
            for idx, img_path in enumerate(img_paths):
                img_ext = os.path.splitext(img_path)[1].lower()
                page_num = idx + 1
                pt0 = time.perf_counter()
                try:
                    ocr_result = _run_ocr(img_ext, img_path)
                    # Prefer whichever engine gave more text
                    tess   = (ocr_result.get("engines") or {}).get("tesseract", {})
                    paddle = (ocr_result.get("engines") or {}).get("paddle_ocr", {})
                    t_text = tess.get("text")   or ""
                    p_text = paddle.get("text") or ""
                    best_text = t_text if len(t_text) >= len(p_text) else p_text
                    engine    = "tesseract" if len(t_text) >= len(p_text) else "paddle"
                    elapsed   = round((time.perf_counter() - pt0) * 1000)
                    all_text_parts.append(f"--- Image {page_num} ---\n{best_text}")
                    page_results.append({
                        "image":      os.path.basename(img_path),
                        "engine":     engine,
                        "chars":      len(best_text),
                        "duration_ms": elapsed,
                        "tesseract_chars":  len(t_text),
                        "paddle_chars":     len(p_text),
                    })
                except Exception as exc:
                    page_results.append({"image": os.path.basename(img_path), "error": str(exc)})

            combined = "\n\n".join(all_text_parts)
            elapsed_total = round((time.perf_counter() - t0) * 1000)
            return {
                "text":         combined,
                "text_chars":   len(combined),
                "tables":       0,
                "images_found": len(img_paths),
                "page_results": page_results,
                "time_ms":      elapsed_total,
            }

        else:  # docx_vlm
            # ── VLM OCR prompt on each image, then rule-parser ─────────────
            from app.services.vlm_service import VLMService
            from app.services.timesheet_rule_parser import TimesheetRuleParser

            svc   = VLMService()
            model = svc.get_available_vision_model()
            if not model:
                return {
                    "text": "", "text_chars": 0, "tables": 0,
                    "images_found": len(img_paths),
                    "error": svc._no_model_result()["error"],
                }

            page_texts: List[str] = []
            for idx, img_path in enumerate(img_paths):
                img_ext  = os.path.splitext(img_path)[1].lower()
                page_num = idx + 1
                pt0 = time.perf_counter()
                try:
                    b64  = svc._load_image_as_b64(img_path)
                    text, err = svc._call_vision_raw_text(model, b64)
                    elapsed   = round((time.perf_counter() - pt0) * 1000)
                    if err:
                        page_results.append({"image": os.path.basename(img_path),
                                             "error": err, "duration_ms": elapsed})
                    else:
                        page_texts.append(text)
                        page_results.append({
                            "image":       os.path.basename(img_path),
                            "chars":       len(text),
                            "duration_ms": elapsed,
                            "preview":     text[:200] + ("…" if len(text) > 200 else ""),
                        })
                except Exception as exc:
                    page_results.append({"image": os.path.basename(img_path), "error": str(exc)})

            raw_text = "\n\n--- IMAGE BREAK ---\n\n".join(page_texts)
            parsed   = TimesheetRuleParser.parse(raw_text)
            elapsed_total = round((time.perf_counter() - t0) * 1000)

            # Build LLM-ready text (same format as regular VLM path)
            text_parts: List[str] = []
            for field in ("employee_name","employee_id","department","manager","company",
                          "period","period_start","period_end","approval_status",
                          "submitted_total_hours","approved_total_hours",
                          "calculated_total_hours","payroll_hours_to_use"):
                val = parsed.get(field)
                if val is not None:
                    text_parts.append(f"{field}: {val}")
            entries = parsed.get("entries") or []
            if entries:
                text_parts.append("validated_entries:")
                for e in entries:
                    parts = [f"{k}: {e[k]}" for k in
                             ("date","day","start_time","end_time","regular_hours",
                              "overtime_hours","hours","task")
                             if e.get(k) is not None]
                    text_parts.append("  " + " | ".join(parts))
            if raw_text:
                text_parts.append("raw_ocr_text:")
                text_parts.append(raw_text)
            text = "\n".join(text_parts)

            return {
                "text":         text,
                "text_chars":   len(text),
                "tables":       0,
                "images_found": len(img_paths),
                "model":        model,
                "page_results": page_results,
                "time_ms":      elapsed_total,
                "vlm_entries":  entries,
                "vlm_meta":     {k: v for k, v in parsed.items()
                                 if k not in ("entries", "rejected_entries")},
                "raw_output":   parsed,
            }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _dispatch_parser(parser: str, path: str, ext: str) -> Dict[str, Any]:
    if parser == "pymupdf":
        r = _parse_pymupdf(path)
        return {"text": r.get("text",""), "text_chars": r.get("text_chars",0), "tables": r.get("tables",0), "raw_output": r}
    if parser == "pdfplumber":
        r = _parse_pdfplumber(path)
        return {"text": r.get("text",""), "text_chars": r.get("text_chars",0), "tables": r.get("tables",0), "raw_output": r}
    if parser == "pypdf":
        r = _parse_pypdf(path)
        if r.get("error"): raise Exception(r["error"])
        return {"text": r.get("text",""), "text_chars": r.get("text_chars",0), "tables": 0, "raw_output": r}
    if parser == "pdfminer":
        r = _parse_pdfminer(path)
        if r.get("error"): raise Exception(r["error"])
        return {"text": r.get("text",""), "text_chars": r.get("text_chars",0), "tables": 0, "raw_output": r}
    if parser == "docling":
        r = _run_docling(path, ext)
        if r.get("error_type") == "MISSING_MODEL_WEIGHTS":
            raise Exception(r.get("message","Docling model weights missing"))
        return {"text": r.get("text",""), "text_chars": r.get("text_chars",0), "tables": r.get("tables_found",0), "raw_output": r}
    if parser == "marker":
        r = _parse_marker(path)
        if r.get("error"): raise Exception(r["error"])
        return {"text": r.get("text",""), "text_chars": r.get("text_chars",0), "tables": 0, "raw_output": r}
    if parser in ("tesseract", "paddle"):
        if parser == "tesseract":
            r = _run_tesseract(path, ext)
        else:
            r = _run_paddleocr(path, ext)
        if r.get("error"):
            raise Exception(r["error"])
        text = r.get("text", "")
        return {
            "text":         text,
            "text_chars":   len(text),
            "tables":       0,
            "page_results": r.get("page_results", []),
            "raw_output":   r,
        }
    if parser == "ocr_vlm":
        return _run_ocr_vlm(path, ext)
    if parser == "vlm":
        r = _run_vlm(path, ext)
        if r.get("error") and not r.get("raw_text"):
            raise Exception(r["error"])

        # The VLM now returns only raw OCR text — no rule-parser, no JSON
        raw_text     = r.get("raw_text") or ""
        page_results = r.get("page_results") or []
        errors       = r.get("errors") or []

        summary_lines = []
        if r.get("model"):
            summary_lines.append(f"Vision model: {r['model']}")
        if r.get("pages_processed"):
            summary_lines.append(f"Pages processed: {r['pages_processed']}")
        for pg in page_results:
            if pg.get("status") == "success":
                summary_lines.append(
                    f"  Page {pg['page']}: {pg.get('chars',0)} chars"
                    + (f" — {pg['preview'][:80]}…" if pg.get("preview") else "")
                )
            else:
                summary_lines.append(f"  Page {pg['page']}: {pg.get('error','unknown error')}")
        if errors:
            summary_lines.append("Errors: " + "; ".join(errors))

        return {
            "text":         raw_text,
            "text_chars":   len(raw_text),
            "tables":       0,
            "page_results": page_results,
            "pages_processed": r.get("pages_processed", 0),
            "model":        r.get("model"),
            "errors":       errors,
            "vlm_summary":  "\n".join(summary_lines),
            "raw_output":   r,
        }
    if parser == "excel":
        from app.services.parsers.excel_parser import ExcelParser
        r = ExcelParser().parse(path); text = r.get("raw_text","") or ""
        return {"text": text, "text_chars": len(text), "tables": len(r.get("raw_tables",[])), "raw_output": r}
    if parser == "csv":
        from app.services.parsers.csv_parser import CsvParser
        r = CsvParser().parse(path); text = r.get("raw_text","") or ""
        return {"text": text, "text_chars": len(text), "tables": len(r.get("raw_tables",[])), "raw_output": r}
    if parser == "docx":
        from app.services.parsers.docx_parser import DocxParser
        r = DocxParser().parse(path)
        text = r.get("raw_text") or ""
        return {"text": text, "text_chars": len(text), "tables": len(r.get("raw_tables") or []), "raw_output": r}

    if parser in ("docx_ocr", "docx_vlm"):
        return _dispatch_docx_image_parser(path, parser)

    # Fallback: raw text read (for .txt, .log, or any unrecognised type)
    if parser == "raw":
        t0 = time.perf_counter()
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            logger.info("raw: %d total chars | first500: %s", len(text), repr(text[:500]))
            return {"text": text, "text_chars": len(text), "tables": 0,
                    "time_ms": round((time.perf_counter()-t0)*1000)}
        except Exception as e:
            return {"error": str(e), "text": "", "text_chars": 0, "time_ms": 0}

    raise HTTPException(400, f"Unknown parser '{parser}'.")


# ── Lab helpers: source analysis, block splitting, entry merge ─────────────────

import re as _re
from datetime import datetime as _dt

# Regex patterns for detecting candidate timesheet rows
_DATE_RE = _re.compile(
    r"""
    \b(?:
        \d{1,2}/\d{1,2}/\d{2,4}                                          # MM/DD/YYYY or DD/MM/YYYY
      | \d{4}-\d{1,2}-\d{1,2}                                             # YYYY-MM-DD
      | \d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}  # DD-Mon-YY
      | (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:\s*,\s*\d{4})?  # Mon DD, YYYY
      | \d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2,4}         # DD Mon YYYY
    )\b
    """,
    _re.IGNORECASE | _re.VERBOSE,
)

_WEEKDAY_RE = _re.compile(
    r'\b(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\b',
    _re.IGNORECASE,
)

_TIME_RE = _re.compile(
    r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b',
)

_WEEKLY_SECTION_RE = _re.compile(
    r"""
    (?:
        Week\s+(?:of|ending|starting|commencing)?\s*\d  # "Week of 01/01"
      | W[/.]?E\.?\s+\d                                  # "W/E 01/01"
      | Week\s+\d+\b                                     # "Week 1", "Week 23"
      | (?:Weekly|Monthly)\s+Summary                     # headers
      | Period\s+\d{1,2}[/-]\d{1,2}                      # "Period 05/01"
    )
    """,
    _re.IGNORECASE | _re.VERBOSE,
)

_PAGE_BREAK_RE = _re.compile(
    r'---\s*PAGE\s*BREAK\s*---|={5,}|-{5,}|\f',
    _re.IGNORECASE,
)


def _count_source_rows(text: str) -> dict:
    """
    Deterministically count candidate timesheet rows in raw text BEFORE calling LLM.
    Returns a dict with:
      - detected_source_row_count  (lines that look like data rows)
      - detected_weekly_section_count
      - detected_date_range_from_source  (min_date → max_date as strings)
      - date_count
    """
    lines = text.splitlines()

    data_rows     = 0
    date_strs     = []
    weekly_sects  = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        has_date    = bool(_DATE_RE.search(stripped))
        has_weekday = bool(_WEEKDAY_RE.search(stripped))
        has_time    = bool(_TIME_RE.search(stripped))
        has_number  = bool(_re.search(r'\b\d+(?:\.\d+)?\b', stripped))

        # A candidate row needs at least a date OR (weekday + number) OR (two times)
        if has_date or (has_weekday and has_number) or (has_time and has_number):
            data_rows += 1
            for m in _DATE_RE.finditer(stripped):
                date_strs.append(m.group())

        if _WEEKLY_SECTION_RE.search(stripped):
            weekly_sects += 1

    # Parse date strings to find range
    parsed_dates = []
    for ds in date_strs:
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d",
                    "%d-%b-%y", "%d-%b-%Y", "%b %d, %Y", "%b %d",
                    "%m/%d/%y", "%d %b %Y"):
            try:
                parsed_dates.append(_dt.strptime(ds.strip(), fmt))
                break
            except ValueError:
                continue

    if parsed_dates:
        min_d = min(parsed_dates).strftime("%Y-%m-%d")
        max_d = max(parsed_dates).strftime("%Y-%m-%d")
        date_range_src = f"{min_d} → {max_d}"
    else:
        date_range_src = "not detected"

    logger.info(
        "source_analysis: %d candidate rows, %d weekly sections, %d dates found, range=%s",
        data_rows, weekly_sects, len(date_strs), date_range_src,
    )
    return {
        "detected_source_row_count":      data_rows,
        "detected_weekly_section_count":  weekly_sects,
        "detected_date_range_from_source": date_range_src,
        "date_count":                     len(date_strs),
    }


def _split_into_blocks(text: str) -> list:
    """
    Split raw text into logical blocks for block-by-block LLM extraction.
    Priority order:
      1. Explicit page breaks (--- PAGE BREAK ---)
      2. Weekly section headers (Week of ..., W/E ..., etc.)
      3. Long separator lines (===== or -----)
      4. Every ~60 non-blank lines as fallback
    Returns a list of non-empty block strings.
    """
    # 1. Try page breaks first
    if _PAGE_BREAK_RE.search(text):
        parts = _PAGE_BREAK_RE.split(text)
        blocks = [p.strip() for p in parts if p.strip() and len(p.strip()) > 50]
        if len(blocks) > 1:
            logger.info("split_blocks: %d blocks via page-break pattern", len(blocks))
            return blocks

    # 2. Try weekly section splits — keep the header with its block
    lines       = text.splitlines()
    blocks      = []
    current     = []
    found_week  = False
    for line in lines:
        if _WEEKLY_SECTION_RE.search(line):
            if current and found_week:
                chunk = "\n".join(current).strip()
                if chunk:
                    blocks.append(chunk)
            current    = [line]
            found_week = True
        else:
            current.append(line)
    if current:
        chunk = "\n".join(current).strip()
        if chunk:
            blocks.append(chunk)

    if len(blocks) > 1:
        logger.info("split_blocks: %d blocks via weekly-section headers", len(blocks))
        return blocks

    # 3. Fallback — every 60 non-blank lines
    chunk_lines_target = 60
    blocks  = []
    current = []
    nb      = 0
    for line in lines:
        current.append(line)
        if line.strip():
            nb += 1
        if nb >= chunk_lines_target:
            chunk = "\n".join(current).strip()
            if chunk:
                blocks.append(chunk)
            current = []
            nb      = 0
    if current:
        chunk = "\n".join(current).strip()
        if chunk:
            blocks.append(chunk)

    if len(blocks) > 1:
        logger.info("split_blocks: %d blocks via line-count fallback", len(blocks))
    else:
        logger.info("split_blocks: no useful split found — using single block")

    return [b for b in blocks if b] or [text]


def _parse_date_safe(d: str) -> "Optional[_dt]":
    """Try common date formats; return None if unparseable."""
    if not d:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y",
                "%d-%b-%y", "%d-%b-%Y", "%b %d, %Y", "%b %d %Y"):
        try:
            return _dt.strptime(d.strip(), fmt)
        except ValueError:
            continue
    return None


def _build_period_prompt_block(period_filter: dict) -> str:
    """
    Given {month: 5, year: 2026}, return a prompt constraint string and
    the (period_start, period_end) as YYYY-MM-DD strings.
    """
    import calendar
    m = int(period_filter.get("month", 0))
    y = int(period_filter.get("year", 0))
    if not (1 <= m <= 12 and 1900 <= y <= 2100):
        return "", None, None
    last_day = calendar.monthrange(y, m)[1]
    ps = f"{y:04d}-{m:02d}-01"
    pe = f"{y:04d}-{m:02d}-{last_day:02d}"
    month_name = _dt(y, m, 1).strftime("%B %Y")
    block = (
        f"\n⚠️  PERIOD CONSTRAINT (STRICT): Extract ONLY entries whose date falls "
        f"within {month_name} ({ps} to {pe}).\n"
        f"   • DO NOT include any entry outside this date range.\n"
        f"   • If an entry date cannot be determined, skip it.\n"
        f"   • Set period_start=\"{ps}\" and period_end=\"{pe}\" in the output.\n"
    )
    return block, ps, pe


def _filter_entries_by_period(entries: list, period_start: str, period_end: str) -> list:
    """Remove any entry whose date falls outside [period_start, period_end]."""
    try:
        ps = _dt.strptime(period_start, "%Y-%m-%d")
        pe = _dt.strptime(period_end,   "%Y-%m-%d")
    except (ValueError, TypeError):
        return entries  # can't parse — don't filter
    filtered = []
    for e in entries:
        d_str = e.get("date") or e.get("work_date") or ""
        d = _parse_date_safe(str(d_str))
        if d and ps <= d <= pe:
            filtered.append(e)
        elif not d:
            # no date at all — keep (may be a summary row) but flag
            filtered.append(e)
    return filtered


def _v2_daily_to_entries(daily_records: list) -> list:
    """Map v2 daily_records → legacy entries list for scoring compatibility."""
    entries = []
    for dr in daily_records:
        if not dr.get("worked"):
            continue
        entries.append({
            "date":           dr.get("date"),
            "in_time":        dr.get("in_time"),
            "out_time":       dr.get("out_time"),
            "break_minutes":  int((dr.get("lunch_hours") or 0) * 60),
            "hours":          float(dr.get("total_hours") or 0),
            "regular_hours":  float(dr.get("regular_hours") or 0),
            "overtime_hours": float(dr.get("overtime_hours") or 0),
            "sick_hours":     float(dr.get("sick_hours") or 0),
            "vacation_hours": float(dr.get("vacation_hours") or 0),
            "holiday_hours":  float(dr.get("holiday_hours") or 0),
            "entry_type":     "WORK",
            "source":         "FILE_EXTRACTED",
            "evidence":       dr.get("evidence"),
        })
    return entries


def _v2_summary_stats(v2: dict) -> dict:
    """Extract scoring stats from a v2 result dict."""
    s   = v2.get("summary", {})
    ot  = v2.get("overtime", {})
    val = v2.get("validation", {})
    dr  = v2.get("daily_records", [])
    worked = [r for r in dr if r.get("worked")]
    dates  = [r["date"] for r in worked if r.get("date")]
    return {
        "entries_found":         len(worked),
        "total_hours":           round(float(s.get("total_payable_hours") or 0), 2),
        "regular_hours":         round(float(s.get("total_regular_hours") or 0), 2),
        "overtime_hours":        round(float(s.get("total_overtime_hours") or 0), 2),
        "sick_hours":            round(float(s.get("total_sick_hours") or 0), 2),
        "vacation_hours":        round(float(s.get("total_vacation_hours") or 0), 2),
        "holiday_hours":         round(float(s.get("total_holiday_hours") or 0), 2),
        "worked_days":           int(s.get("worked_days_count") or len(worked)),
        "period_start":          min(dates) if dates else None,
        "period_end":            max(dates) if dates else None,
        "unique_dates":          len(set(dates)),
        "date_range":            f"{min(dates)} → {max(dates)}" if dates else "not detected",
        "has_overtime":          bool(ot.get("has_overtime")),
        "validation_status":     val.get("validation_status", "unclear"),
        "document_total":        val.get("document_total"),
        "calculated_total":      val.get("calculated_total"),
        "manager_approval":      v2.get("manager_approval", {}).get("status", "not_found"),
    }


def _hours_from_entry(e: dict) -> float:
    """
    Deterministically compute worked hours for one entry.
    Priority: calculate from in/out times → use reliable hours column.
    """
    # 1. Calculate from punch times if both present
    in_t  = (e.get("in_time")  or "").strip()
    out_t = (e.get("out_time") or "").strip()
    if in_t and out_t:
        try:
            def _to_mins(ts: str) -> int:
                ts = ts.upper().replace(" ", "")
                pm = ts.endswith("PM"); am = ts.endswith("AM")
                ts = ts.rstrip("APM").strip()
                h, m = (ts.split(":") + ["0"])[:2]
                mins = int(h) * 60 + int(m)
                if pm and int(h) != 12:
                    mins += 720
                if am and int(h) == 12:
                    mins -= 720
                return mins
            i_mins = _to_mins(in_t)
            o_mins = _to_mins(out_t)
            if o_mins < i_mins:          # crosses noon → add 12h
                o_mins += 720
            brk = float(e.get("break_minutes") or 0)
            calc = max((o_mins - i_mins - brk) / 60, 0.0)
            # Sanity check: >16h in a single punch likely wrong
            if 0 < calc <= 16:
                return round(calc, 2)
        except Exception:
            pass

    # 2. Use hours columns in priority order
    for k in ("hours", "regular_hours", "total_hours", "billable_hours", "worked_hours"):
        try:
            v = float(e.get(k) or 0)
            if 0 < v <= 24:
                return v
        except (TypeError, ValueError):
            pass
    return 0.0


def _merge_entries(base: list, new: list) -> list:
    """
    Append new entries to base, deduplicating by (date, in_time, out_time).
    If a duplicate is found, keep the one with more hours.
    """
    seen: dict = {}
    for e in base:
        key = (
            str(e.get("date") or ""),
            str(e.get("in_time") or ""),
            str(e.get("out_time") or ""),
        )
        seen[key] = e

    for e in new:
        key = (
            str(e.get("date") or ""),
            str(e.get("in_time") or ""),
            str(e.get("out_time") or ""),
        )
        if key in seen:
            # Keep whichever entry has more hours
            existing_h = _hours_from_entry(seen[key])
            new_h      = _hours_from_entry(e)
            if new_h > existing_h:
                seen[key] = e
        else:
            seen[key] = e

    merged = sorted(seen.values(), key=lambda x: str(x.get("date") or ""))
    return merged


def _extract_with_blocks(text: str, filename: str, svc, source_rows: int,
                         period_block: str = "") -> tuple:
    """
    Try a single-pass LLM extraction. If returned entries < 70% of source rows,
    split into blocks and re-extract, merging results.
    Returns: (entries, meta, strategy, block_count)
    period_block: optional period constraint injected before raw text in each prompt.
    """
    def _inject_period(raw: str) -> str:
        """Prepend the period constraint to the raw text so each LLM call sees it."""
        if not period_block:
            return raw
        return period_block + "\n" + raw

    # Single pass first (no verify — we handle verification after merge)
    single = svc.extract_timesheet_json(
        raw_text=_inject_period(text),
        file_metadata={"filename": filename},
        verify=False,
    )
    entries = []
    meta    = {}
    if isinstance(single, dict):
        entries = single.get("entries") or []
        meta    = {k: v for k, v in single.items() if k != "entries"}
    elif isinstance(single, list):
        entries = single

    threshold = max(1, int(source_rows * 0.70)) if source_rows > 0 else 0

    if source_rows == 0 or len(entries) >= threshold:
        logger.info(
            "extract_blocks: single-pass returned %d entries (source_rows=%d) — sufficient",
            len(entries), source_rows,
        )
        return entries, meta, "single_pass", 1

    # Single pass insufficient — try block-by-block
    logger.warning(
        "extract_blocks: single-pass returned only %d entries vs %d source rows "
        "— splitting into blocks",
        len(entries), source_rows,
    )
    blocks = _split_into_blocks(text)
    if len(blocks) <= 1:
        logger.info("extract_blocks: no useful split — returning single-pass result")
        return entries, meta, "single_pass_no_split", 1

    all_entries = list(entries)   # start from single-pass results
    for i, block in enumerate(blocks):
        logger.info("extract_blocks: block %d/%d  chars=%d", i + 1, len(blocks), len(block))
        block_result = svc.extract_timesheet_json(
            raw_text=_inject_period(block),
            file_metadata={"filename": filename},
            verify=False,
        )
        block_entries = []
        if isinstance(block_result, dict):
            block_entries = block_result.get("entries") or []
            if not meta.get("employee_name") and block_result.get("employee_name"):
                meta["employee_name"] = block_result["employee_name"]
        elif isinstance(block_result, list):
            block_entries = block_result

        before = len(all_entries)
        all_entries = _merge_entries(all_entries, block_entries)
        logger.info(
            "extract_blocks: block %d added %d new entries (total %d → %d)",
            i + 1, len(block_entries), before, len(all_entries),
        )

    logger.info(
        "extract_blocks: block-pass complete — %d total entries from %d blocks",
        len(all_entries), len(blocks),
    )
    return all_entries, meta, "block_pass", len(blocks)


# ── Step 3: Run LLM extraction ─────────────────────────────────────────────────

@router.post("/lab/{session_id}/run-llm")
async def lab_run_llm(session_id: str, body: dict):
    """
    Extract timesheet data via LLM from parsed text.
    Body: { "text": "...", "parser_used": "pdfplumber" }

    Uses StreamingResponse + keepalive newlines so the Next.js proxy never
    times out on slow LLM inference (same pattern as lab_run_parser).
    """
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse as _SR

    s    = _get_session(session_id)
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "No text provided. Run a parser in Step 2 first.")
    period_filter = body.get("period_filter") or {}  # {month: int, year: int}

    def _do_llm() -> dict:
        import uuid as _uuid_mod
        import httpx as _httpx
        t0         = time.perf_counter()
        request_id = _uuid_mod.uuid4().hex[:10]
        try:
            from app.services.llm_service import (
                LLMService, build_lab_prompts
            )
            from app.core.config import settings

            logger.info("[req:%s] START v2  file=%s  text_chars=%d",
                        request_id, s["filename"], len(text))

            if not settings.LLM_ENABLED:
                return {"status": "skipped", "note": "LLM_ENABLED=false",
                        "request_id": request_id,
                        "entries": [], "summary": {}, "duration_ms": 0}

            # ── 1. Log source text diagnostics ──────────────────────────────
            logger.info("[req:%s] text first1000: %s", request_id, repr(text[:1000]))
            logger.info("[req:%s] text last1000:  %s", request_id, repr(text[-1000:]))

            # ── 2. Pre-LLM source row detection ─────────────────────────────
            source_stats = _count_source_rows(text)
            src_rows     = source_stats["detected_source_row_count"]
            logger.info("[req:%s] source_analysis: rows=%d  date_range=%s",
                        request_id, src_rows,
                        source_stats["detected_date_range_from_source"])

            # ── 3. Build v2 prompts with period constraint ───────────────────
            overtime_policy = body.get("overtime_policy", "")
            sys_prompt, user_prompt, target_ym, pf_start, pf_end = build_lab_prompts(
                text, period_filter, overtime_policy
            )
            logger.info("[req:%s] period=%s → %s  target_month=%s  prompt_chars=%d",
                        request_id, pf_start, pf_end, target_ym, len(user_prompt))

            # ── 4. Call LLM (qwen3:14b default for test-lab) ────────────────
            lab_model = "qwen3:14b"
            logger.info("[req:%s] calling model=%s", request_id, lab_model)
            r = _httpx.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model":  lab_model,
                    "system": sys_prompt,
                    "prompt": "/no_think\n" + user_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 16384,
                        "num_ctx":     65536,
                    },
                },
                timeout=max(settings.LLM_TIMEOUT, 900),  # 15 min max — qwen3:14b can be slow
            )
            elapsed_llm = round((time.perf_counter() - t0) * 1000)

            if r.status_code != 200:
                raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")

            raw_response = r.json().get("response", "")
            logger.info("[req:%s] raw_response_chars=%d  elapsed=%dms",
                        request_id, len(raw_response), elapsed_llm)

            # ── 5. Parse v2 JSON schema ──────────────────────────────────────
            svc    = LLMService()
            parsed = svc._parse_json(raw_response)  # type: ignore[attr-defined]

            if not parsed:
                raise RuntimeError("LLM returned no parseable JSON")

            # Accept both v2 (daily_records) and fallback (entries)
            if "daily_records" not in parsed and "entries" not in parsed:
                raise RuntimeError(
                    f"JSON missing 'daily_records' and 'entries' keys. "
                    f"Keys found: {list(parsed.keys())}"
                )

            # ── 6. Convert daily_records → entries for compat ────────────────
            if "daily_records" in parsed:
                entries = _v2_daily_to_entries(parsed["daily_records"])
                v2_result = parsed
            else:
                # Old-style response — wrap it
                entries = parsed.get("entries", [])
                v2_result = None

            logger.info("[req:%s] v2_schema=%s  worked_days=%d",
                        request_id, "daily_records" in parsed, len(entries))

            # ── 7. Post-filter to selected period ────────────────────────────
            if pf_start and pf_end:
                before = len(entries)
                entries = _filter_entries_by_period(entries, pf_start, pf_end)
                if v2_result and "daily_records" in v2_result:
                    v2_result["daily_records"] = [
                        dr for dr in v2_result["daily_records"]
                        if _parse_date_safe(dr.get("date", "")) is not None
                        and pf_start <= dr["date"] <= pf_end
                    ]
                if len(entries) < before:
                    logger.info("[req:%s] period_filter removed %d out-of-range entries",
                                request_id, before - len(entries))

            # ── 8. Build summary from v2 or legacy ──────────────────────────
            if v2_result:
                stats = _v2_summary_stats(v2_result)
            else:
                stats = {}
                for e in entries:
                    h = _hours_from_entry(e)
                    e["_computed_hours"] = h
                    stats["total_hours"] = stats.get("total_hours", 0) + h
                stats["entries_found"] = len(entries)

            # Period from actual entry dates
            dates = [e.get("date") for e in entries if e.get("date")]
            valid_dates = [_parse_date_safe(d) for d in dates if _parse_date_safe(d)]
            period_start = min(valid_dates).strftime("%Y-%m-%d") if valid_dates else pf_start
            period_end   = max(valid_dates).strftime("%Y-%m-%d") if valid_dates else pf_end
            employee_name = (
                (v2_result or {}).get("employee_name")
                or (parsed.get("employee_name"))
            )

            # ── 9. Completeness validation ───────────────────────────────────
            completeness_pct = round(len(entries) / src_rows * 100, 1) if src_rows > 0 else 100.0
            incomplete  = src_rows > 0 and len(entries) < src_rows * 0.70
            warning_msg = None
            if incomplete:
                warning_msg = (
                    f"Incomplete extraction: source has {src_rows} candidate rows "
                    f"but LLM returned only {len(entries)} worked entries "
                    f"({completeness_pct}%). "
                    f"Some rows may have been missed."
                )
                logger.warning("[req:%s] %s", request_id, warning_msg)

            # ── 10. Final log ─────────────────────────────────────────────────
            logger.info(
                "[req:%s] FINAL v2  entries=%d  period=%s→%s  total=%.2fh  "
                "validation=%s  manager=%s  complete=%s",
                request_id, len(entries), period_start, period_end,
                float(stats.get("total_hours", 0)),
                stats.get("validation_status", "?"),
                stats.get("manager_approval", "?"),
                not incomplete,
            )

            status = "warning" if incomplete else "success"

            summary = {
                "entries_found":      len(entries),
                "total_hours":        round(float(stats.get("total_hours", 0)), 2),
                "regular_hours":      round(float(stats.get("regular_hours", 0)), 2),
                "overtime_hours":     round(float(stats.get("overtime_hours", 0)), 2),
                "sick_hours":         round(float(stats.get("sick_hours", 0)), 2),
                "vacation_hours":     round(float(stats.get("vacation_hours", 0)), 2),
                "holiday_hours":      round(float(stats.get("holiday_hours", 0)), 2),
                "worked_days":        int(stats.get("worked_days", len(entries))),
                "date_range":         f"{period_start} → {period_end}" if period_start else "not detected",
                "unique_dates":       len(set(dates)),
                "period_start":       period_start,
                "period_end":         period_end,
                "src_candidate_rows": src_rows,
                "completeness_pct":   completeness_pct,
                "extraction_strategy": "v2_direct",
                "block_count":        1,
                "validation_passed":  not incomplete,
                "validation_status":  stats.get("validation_status"),
                "manager_approval":   stats.get("manager_approval"),
                "period_filter":      f"{pf_start} → {pf_end}" if pf_start else None,
                "target_month":       target_ym,
            }

            return {
                "request_id":     request_id,
                "session_id":     session_id,
                "parser_used":    body.get("parser_used", "unknown"),
                "status":         status,
                "duration_ms":    round((time.perf_counter() - t0) * 1000),
                "provider":       "ollama",
                "model":          lab_model,
                "prompt_preview": user_prompt[:2000] + ("…" if len(user_prompt) > 2000 else ""),
                "employee_name":  employee_name,
                "entries":        entries,
                "v2_result":      v2_result,
                "extraction_strategy": "v2_direct",
                "warning":        warning_msg,
                "source_analysis": source_stats,
                "summary":        summary,
            }

        except Exception as exc:
            logger.exception("[req:%s] extraction failed", request_id)
            return {
                "request_id":  request_id,
                "session_id":  session_id,
                "status":      "error",
                "duration_ms": round((time.perf_counter() - t0) * 1000),
                "error":       str(exc),
                "entries":     [],
                "summary":     {},
            }

    async def _stream():
        import json as _json
        t0   = time.perf_counter()
        loop = asyncio.get_running_loop()

        # Immediately notify frontend that work has started
        yield (_json.dumps({"type": "start",
                             "message": f"Starting extraction with qwen3:14b…",
                             "elapsed_ms": 0}) + "\n").encode()

        future = loop.run_in_executor(None, _do_llm)

        # Send typed progress pings every 5 s — frontend renders a live timer
        ping_count = 0
        while not future.done():
            try:
                await asyncio.wait_for(asyncio.shield(future), timeout=5.0)
            except asyncio.TimeoutError:
                ping_count += 1
                elapsed = round((time.perf_counter() - t0) * 1000)
                yield (_json.dumps({
                    "type":       "progress",
                    "elapsed_ms": elapsed,
                    "message":    f"LLM is processing… {elapsed // 1000}s elapsed",
                    "ping":       ping_count,
                }) + "\n").encode()
            except Exception:
                break

        # Collect result
        try:
            result = await future
        except Exception as exc:
            result = {
                "session_id": session_id,
                "status":     "error",
                "duration_ms": round((time.perf_counter() - t0) * 1000),
                "error":      str(exc),
                "entries":    [],
                "summary":    {},
            }

        yield (_json.dumps({"type": "result", **result}) + "\n").encode()

    return _SR(_stream(), media_type="application/x-ndjson")


# ── Session info ───────────────────────────────────────────────────────────────

@router.get("/lab/{session_id}/info")
async def lab_session_info(session_id: str):
    s = _get_session(session_id)
    return {"session_id": session_id, "filename": s["filename"],
            "ext": s["ext"], "size_kb": s["size_kb"],
            "available_parsers": _get_available_parsers(s["ext"])}


# ═══════════════════════════════════════════════════════════════════════════════
# ── Multi-model Benchmark (Step 3b) ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

# Model catalog — maps design-doc models to Ollama equivalents.
# Role: primary | fast_helper | review | fallback
LAB_MODEL_CATALOG: list = [
    {
        "id":          "qwen2.5:7b",
        "name":        "Qwen2.5 7B",
        "description": "Current default — solid general timesheet extraction",
        "role":        "primary",
        "size_gb":     4.7,
        "design_doc":  None,
    },
    {
        "id":          "qwen3:8b",
        "name":        "Qwen3 8B",
        "description": "Latest Qwen3 — fast helper with improved instruction following",
        "role":        "fast_helper",
        "size_gb":     5.2,
        "design_doc":  "nvidia/Qwen3-14B-FP4 (lite substitute)",
    },
    {
        "id":          "qwen3:14b",
        "name":        "Qwen3 14B",
        "description": "Design-doc fast helper (nvidia/Qwen3-14B-FP4 equivalent)",
        "role":        "fast_helper",
        "size_gb":     9.3,
        "design_doc":  "nvidia/Qwen3-14B-FP4",
    },
    {
        "id":          "qwen3:32b",
        "name":        "Qwen3 32B",
        "description": "Design-doc review model (nvidia/Qwen3-32B-FP4 equivalent)",
        "role":        "review",
        "size_gb":     20.0,
        "design_doc":  "nvidia/Qwen3-32B-FP4",
    },
    {
        "id":          "nemotron-mini",
        "name":        "Nemotron Mini 4B",
        "description": "NVIDIA Nemotron — fast, reasoning-optimised inference",
        "role":        "fast",
        "size_gb":     2.7,
        "design_doc":  "nvidia/Nemotron-3-Nano (substitute)",
    },
    {
        "id":          "llama3.2:1b",
        "name":        "Llama 3.2 1B",
        "description": "Micro fallback model — lowest latency baseline",
        "role":        "fallback",
        "size_gb":     1.3,
        "design_doc":  None,
    },
]


def _ollama_list_models() -> list:
    """Return list of model names currently pulled in Ollama."""
    try:
        import httpx
        from app.core.config import settings
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=10)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


@router.get("/lab/models")
async def lab_list_models():
    """Return the benchmark model catalog annotated with pull status."""
    pulled = _ollama_list_models()

    def _pulled(model_id: str) -> bool:
        # Exact match OR prefix match (e.g. "qwen3:14b" in "qwen3:14b-q4_K_M")
        return any(p == model_id or p.startswith(model_id.split(":")[0] + ":") and
                   model_id.split(":")[-1] in p
                   for p in pulled)

    catalog = []
    for m in LAB_MODEL_CATALOG:
        entry = dict(m)
        entry["pulled"]  = _pulled(m["id"])
        entry["default"] = (m["id"] == "qwen2.5:7b")
        catalog.append(entry)

    return {"models": catalog, "pulled_raw": pulled}


@router.post("/lab/models/{model_id:path}/pull")
async def lab_pull_model(model_id: str):
    """
    Pull a model into Ollama (streaming progress via StreamingResponse).
    Frontend polls this until done.
    """
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse as _SR

    async def _stream():
        try:
            import httpx
            from app.core.config import settings
            logger.info("lab_pull_model: pulling %s", model_id)
            async with httpx.AsyncClient(timeout=600) as client:
                async with client.stream(
                    "POST",
                    f"{settings.OLLAMA_BASE_URL}/api/pull",
                    json={"name": model_id, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            yield (line + "\n").encode()
            yield _json.dumps({"status": "success", "model": model_id}).encode()
        except Exception as exc:
            yield _json.dumps({"status": "error", "error": str(exc)}).encode()

    return _SR(_stream(), media_type="application/x-ndjson")


@router.post("/lab/models/{model_id:path}/warmup")
async def lab_warmup_model(model_id: str):
    """
    Warm up a model by sending a minimal generate request.
    Ollama loads the model weights into GPU memory and keeps them resident.
    """
    import asyncio
    from fastapi.responses import StreamingResponse as _SR
    import json as _json

    def _do_warmup() -> dict:
        try:
            import httpx
            from app.core.config import settings
            logger.info("lab_warmup_model: warming %s", model_id)
            t0 = time.perf_counter()
            r  = httpx.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model":  model_id,
                    "prompt": "Hello",
                    "stream": False,
                    "options": {"num_predict": 1, "temperature": 0},
                },
                timeout=300,
            )
            elapsed = round((time.perf_counter() - t0) * 1000)
            if r.status_code == 200:
                logger.info("lab_warmup_model: %s warm in %d ms", model_id, elapsed)
                return {"status": "warm", "model": model_id, "elapsed_ms": elapsed}
            return {"status": "error", "model": model_id,
                    "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "model": model_id, "error": str(exc)}

    async def _stream():
        loop   = asyncio.get_running_loop()
        future = loop.run_in_executor(None, _do_warmup)
        while not future.done():
            try:
                await asyncio.wait_for(asyncio.shield(future), timeout=5.0)
            except asyncio.TimeoutError:
                yield b"\n"
            except Exception:
                break
        try:
            result = await future
        except Exception as exc:
            result = {"status": "error", "model": model_id, "error": str(exc)}
        yield _json.dumps(result).encode()

    return _SR(_stream(), media_type="application/json")


@router.post("/lab/{session_id}/run-llm-bench")
async def lab_run_llm_bench(session_id: str, body: dict):
    """
    Run LLM extraction against multiple models and return a comparison.
    Body: { "text": "...", "parser_used": "...", "models": ["qwen2.5:7b", "qwen3:14b"] }
    Runs models sequentially (avoids OOM on shared GPU memory).
    Returns all results including per-model metrics for comparison.
    """
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse as _SR

    s          = _get_session(session_id)
    text       = (body.get("text") or "").strip()
    model_ids  = body.get("models") or ["qwen3:14b"]
    parser_used = body.get("parser_used", "unknown")
    period_filter  = body.get("period_filter") or {}
    overtime_policy = body.get("overtime_policy", "")

    if not text:
        raise HTTPException(400, "No text provided.")
    if not model_ids:
        raise HTTPException(400, "No models specified.")

    # Build v2 prompts once — shared across all models in the benchmark
    from app.services.llm_service import build_lab_prompts, LLMService
    sys_prompt, user_prompt, target_ym, pf_start, pf_end = build_lab_prompts(
        text, period_filter, overtime_policy
    )
    src_stats = _count_source_rows(text)
    src_rows  = src_stats["detected_source_row_count"]

    # Deduplicate preserving order
    seen_m: set = set()
    model_ids = [m for m in model_ids if not (m in seen_m or seen_m.add(m))]  # type: ignore

    def _run_one_model(model_id: str) -> dict:
        """Run extraction for a single model using v2 system+user prompts."""
        import httpx
        import uuid as _uuid_mod
        from app.core.config import settings

        rid = _uuid_mod.uuid4().hex[:8]
        t0  = time.perf_counter()
        logger.info("[bench:%s] START v2  model=%s  text_chars=%d  period=%s→%s",
                    rid, model_id, len(text), pf_start or "any", pf_end or "any")

        try:
            # Use pre-built v2 system + user prompts
            r = httpx.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model":  model_id,
                    "system": sys_prompt,
                    "prompt": "/no_think\n" + user_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 8192,
                        "num_ctx":     32768,
                    },
                },
                timeout=max(settings.LLM_TIMEOUT, 300),
            )
            elapsed = round((time.perf_counter() - t0) * 1000)

            if r.status_code != 200:
                return {
                    "model_id": model_id, "status": "error",
                    "error": f"HTTP {r.status_code}: {r.text[:200]}",
                    "duration_ms": elapsed, "entries": [], "summary": {},
                }

            raw_response = r.json().get("response", "")
            logger.debug("[bench:%s] model=%s  response_chars=%d",
                         rid, model_id, len(raw_response))

            # Parse v2 JSON schema
            svc    = LLMService()
            parsed = svc._parse_json(raw_response)  # type: ignore[attr-defined]

            if not parsed:
                return {
                    "model_id": model_id, "status": "parse_failed",
                    "error": "Could not parse JSON from response",
                    "raw_preview": raw_response[:500],
                    "duration_ms": elapsed, "entries": [], "summary": {},
                }

            # Accept v2 (daily_records) or legacy (entries)
            if "daily_records" in parsed:
                entries   = _v2_daily_to_entries(parsed["daily_records"])
                v2_result = parsed
                employee_name = parsed.get("employee_name")
            elif "entries" in parsed:
                entries   = parsed.get("entries", [])
                v2_result = None
                employee_name = parsed.get("employee_name")
            else:
                return {
                    "model_id": model_id, "status": "parse_failed",
                    "error": f"No 'daily_records' or 'entries' in response. Keys: {list(parsed.keys())}",
                    "raw_preview": raw_response[:500],
                    "duration_ms": elapsed, "entries": [], "summary": {},
                }

            # Apply period post-filter
            if pf_start and pf_end:
                before_filter = len(entries)
                entries = _filter_entries_by_period(entries, pf_start, pf_end)
                if v2_result and "daily_records" in v2_result:
                    v2_result["daily_records"] = [
                        dr for dr in v2_result["daily_records"]
                        if _parse_date_safe(dr.get("date","")) is not None
                        and pf_start <= dr["date"] <= pf_end
                    ]
                if len(entries) < before_filter:
                    logger.info("[bench:%s] period_filter removed %d out-of-range entries",
                                rid, before_filter - len(entries))

            # Build summary
            if v2_result:
                stats = _v2_summary_stats(v2_result)
            else:
                total_h = 0.0; reg_h = 0.0; ot_h = 0.0; dates: list = []
                for e in entries:
                    h = _hours_from_entry(e)
                    e["_computed_hours"] = h
                    try:
                        reg = float(e.get("regular_hours") or 0)
                        ot  = float(e.get("overtime_hours") or 0)
                        if reg or ot:
                            reg_h += reg; ot_h += ot
                        else:
                            reg_h += h
                    except (TypeError, ValueError):
                        reg_h += h
                    total_h += h
                    d = e.get("date") or e.get("work_date")
                    if d: dates.append(str(d))
                valid_dates = [x for x in (_parse_date_safe(d) for d in dates) if x]
                ps = min(valid_dates).strftime("%Y-%m-%d") if valid_dates else pf_start
                pe = max(valid_dates).strftime("%Y-%m-%d") if valid_dates else pf_end
                stats = {
                    "entries_found": len(entries),
                    "total_hours":   round(total_h, 2),
                    "regular_hours": round(reg_h, 2),
                    "overtime_hours":round(ot_h, 2),
                    "period_start":  ps,
                    "period_end":    pe,
                    "unique_dates":  len(set(dates)),
                    "date_range":    f"{ps} → {pe}" if ps else "not detected",
                }

            completeness = round(len(entries) / src_rows * 100, 1) if src_rows > 0 else None

            logger.info(
                "[bench:%s] model=%s  entries=%d  total_h=%.2f  period=%s→%s  "
                "completeness=%s%%  validation=%s  duration=%dms",
                rid, model_id, len(entries),
                float(stats.get("total_hours", 0)),
                stats.get("period_start"), stats.get("period_end"),
                completeness,
                stats.get("validation_status","?"),
                elapsed,
            )

            return {
                "model_id":      model_id,
                "status":        "success",
                "duration_ms":   elapsed,
                "employee_name": employee_name,
                "entries":       entries,
                "v2_result":     v2_result,
                "raw_response_chars": len(raw_response),
                "summary": {
                    "entries_found":      len(entries),
                    "total_hours":        round(float(stats.get("total_hours", 0)), 2),
                    "regular_hours":      round(float(stats.get("regular_hours", 0)), 2),
                    "overtime_hours":     round(float(stats.get("overtime_hours", 0)), 2),
                    "sick_hours":         round(float(stats.get("sick_hours", 0)), 2),
                    "vacation_hours":     round(float(stats.get("vacation_hours", 0)), 2),
                    "holiday_hours":      round(float(stats.get("holiday_hours", 0)), 2),
                    "period_start":       stats.get("period_start"),
                    "period_end":         stats.get("period_end"),
                    "unique_dates":       stats.get("unique_dates", 0),
                    "date_range":         stats.get("date_range","not detected"),
                    "completeness_pct":   completeness,
                    "src_candidate_rows": src_rows,
                    "validation_status":  stats.get("validation_status"),
                    "manager_approval":   stats.get("manager_approval"),
                    "has_overtime":       stats.get("has_overtime", False),
                    "target_month":       target_ym,
                },
            }

        except Exception as exc:
            elapsed = round((time.perf_counter() - t0) * 1000)
            logger.exception("[bench:%s] model=%s FAILED", rid, model_id)
            return {
                "model_id": model_id, "status": "error",
                "error": str(exc), "duration_ms": elapsed,
                "entries": [], "summary": {},
            }

    # ── Real-time NDJSON stream ─────────────────────────────────────────────
    # Each line is a complete JSON object terminated by \n.
    # Line types:
    #   {"type":"start",  "total":N, "models":[...]}
    #   {"type":"running","model":"...","index":N,"total":N}
    #   {"type":"result", "model":"...","index":N,"total":N,"result":{...}}
    #   {"type":"complete","results":[...],"best_model":"...","duration_ms":N}
    #   {"type":"error",  "error":"..."}
    #
    # The frontend reads lines as they arrive; the last "complete" line
    # contains the full comparison result.  This keeps proxies alive because
    # data flows the moment each model finishes (no silent wait).
    async def _stream():
        t0      = time.perf_counter()
        results: list = []

        # ── announce start ───────────────────────────────────────────────
        yield (_json.dumps({
            "type": "start",
            "total": len(model_ids),
            "models": model_ids,
        }) + "\n").encode()

        loop = asyncio.get_running_loop()

        for idx, mid in enumerate(model_ids):
            # ── tell frontend which model is now running ──────────────────
            yield (_json.dumps({
                "type": "running",
                "model": mid,
                "index": idx,
                "total": len(model_ids),
            }) + "\n").encode()

            logger.info("bench: running model %s (%d/%d)", mid, idx + 1, len(model_ids))

            try:
                r = await loop.run_in_executor(None, _run_one_model, mid)
            except Exception as exc:
                r = {
                    "model_id": mid, "status": "error",
                    "error": str(exc), "duration_ms": 0,
                    "entries": [], "summary": {},
                }

            results.append(r)

            # ── stream this model's result immediately ────────────────────
            yield (_json.dumps({
                "type":   "result",
                "model":  mid,
                "index":  idx,
                "total":  len(model_ids),
                "result": r,
            }) + "\n").encode()

        # ── score + pick best ────────────────────────────────────────────
        best_idx   = 0
        best_score = -1
        for i, r in enumerate(results):
            s_r     = r.get("summary", {})
            entries = s_r.get("entries_found", 0)
            comp    = s_r.get("completeness_pct") or 0
            dur_ms  = r.get("duration_ms", 99999)
            score   = entries * 10 + comp - dur_ms / 1000
            r["_score"] = round(score, 2)
            if score > best_score:
                best_score = score
                best_idx   = i

        if results:
            results[best_idx]["_recommended"] = True

        # ── final summary line ────────────────────────────────────────────
        yield (_json.dumps({
            "type":        "complete",
            "session_id":  session_id,
            "parser_used": parser_used,
            "models_run":  len(results),
            "results":     results,
            "best_model":  results[best_idx]["model_id"] if results else None,
            "duration_ms": round((time.perf_counter() - t0) * 1000),
        }) + "\n").encode()

    return _SR(_stream(), media_type="application/x-ndjson")
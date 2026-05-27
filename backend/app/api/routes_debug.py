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
        doc = fitz.open(path)
        text = "\n".join(p.get_text("text") for p in doc)
        pages = len(doc)
        doc.close()
        return {"text": text[:5000], "text_chars": len(text), "pages": pages,
                "tables": 0, "time_ms": round((time.perf_counter()-t0)*1000)}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0, "time_ms": round((time.perf_counter()-t0)*1000)}


def _parse_pdfplumber(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        import pdfplumber
        texts, tables_found = [], 0
        with pdfplumber.open(path) as pdf:
            for pg in pdf.pages:
                t = pg.extract_text() or ""
                texts.append(t)
                tbls = pg.extract_tables() or []
                tables_found += len([t for t in tbls if t and len(t) > 1])
        text = "\n".join(texts)
        return {"text": text[:5000], "text_chars": len(text), "tables": tables_found,
                "time_ms": round((time.perf_counter()-t0)*1000)}
    except Exception as e:
        return {"error": str(e), "text": "", "text_chars": 0, "time_ms": round((time.perf_counter()-t0)*1000)}


def _parse_pypdf(path: str) -> Dict:
    t0 = time.perf_counter()
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        return {"text": text[:5000], "text_chars": len(text),
                "pages": len(reader.pages), "tables": 0,
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
        return {"text": text[:5000], "text_chars": len(text), "tables": 0,
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

def _run_ocr(ext: str, path: str) -> Dict:
    results = {}

    # Tesseract
    try:
        import pytesseract
        from PIL import Image
        import fitz
        if ext == ".pdf":
            doc = fitz.open(path)
            texts = []
            for i in range(min(len(doc), 3)):
                pix = doc[i].get_pixmap(dpi=150)
                tmp = path + f"_ocr_p{i}.png"
                pix.save(tmp)
                texts.append(pytesseract.image_to_string(Image.open(tmp)))
                os.remove(tmp)
            text = "\n".join(texts)
        else:
            text = pytesseract.image_to_string(Image.open(path))
        results["tesseract"] = {"text": text[:3000], "text_chars": len(text)}
    except Exception as e:
        results["tesseract"] = {"error": str(e), "text": "", "text_chars": 0}

    # PaddleOCR
    try:
        from paddleocr import PaddleOCR
        from app.core.config import settings
        import fitz
        ocr = PaddleOCR(use_angle_cls=True, lang="en", use_gpu=settings.OCR_USE_GPU, show_log=False)
        if ext == ".pdf":
            doc = fitz.open(path)
            all_lines = []
            for i in range(min(len(doc), 3)):
                pix = doc[i].get_pixmap(dpi=150)
                tmp = path + f"_paddle_p{i}.png"
                pix.save(tmp)
                data = ocr.ocr(tmp, cls=True)
                if data and data[0]:
                    all_lines.extend(item[1][0] for item in data[0] if item and len(item) >= 2)
                os.remove(tmp)
            text = "\n".join(all_lines)
        else:
            data = ocr.ocr(path, cls=True)
            lines = []
            if data and data[0]:
                lines = [item[1][0] for item in data[0] if item and len(item) >= 2]
            text = "\n".join(lines)
        results["paddle_ocr"] = {"text": text[:3000], "text_chars": len(text), "lines": len(text.splitlines())}
    except Exception as e:
        results["paddle_ocr"] = {"error": str(e), "text": "", "text_chars": 0}

    best_text = max(
        [results.get("tesseract", {}), results.get("paddle_ocr", {})],
        key=lambda r: r.get("text_chars", 0),
    ).get("text", "")

    return {"engines": results, "best_text": best_text, "text": best_text}


# ── Stage 5: VLM Vision ───────────────────────────────────────────────────────

def _run_vlm(path: str, ext: str) -> Dict:
    from app.services.vlm_service import VLMService
    svc = VLMService()
    if ext in IMAGE_EXTS:
        return svc.extract_from_image_file(path, ext)
    elif ext == ".pdf":
        return svc.extract_from_pdf(path, max_pages=5)
    return {"error": f"VLM not applicable for {ext}", "entries": []}


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
        return {
            "text":           md_text[:5000] + ("…" if len(md_text) > 5000 else ""),
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
        ]
    if ext in IMAGE_EXTS:
        return [
            {"id": "tesseract", "name": "Tesseract",  "desc": "Classic OCR engine",             "category": "ocr"},
            {"id": "paddle",    "name": "PaddleOCR",  "desc": "GPU-accelerated, high accuracy", "category": "ocr"},
            {"id": "vlm",       "name": "VLM Vision", "desc": "Vision LLM understands context", "category": "vlm"},
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
    SLOW_PARSERS = {"vlm", "docling", "marker"}

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
        r = _run_ocr(ext, path)
        key = "tesseract" if parser == "tesseract" else "paddle_ocr"
        eng = (r.get("engines") or {}).get(key, {})
        if eng.get("error"): raise Exception(eng["error"])
        text = eng.get("text","")
        return {"text": text, "text_chars": len(text), "tables": 0, "raw_output": eng}
    if parser == "vlm":
        r = _run_vlm(path, ext)
        if r.get("error") and not r.get("raw_text") and not r.get("entries"):
            raise Exception(r["error"])

        # raw_text is the VLM OCR output — this is what goes to the LLM stage
        raw_text = r.get("raw_text") or ""

        # Build a rich text block for the LLM stage:
        # header fields + validated entries + raw OCR
        text_parts: List[str] = []
        for field in ("employee_name", "employee_id", "department", "manager", "company",
                      "period", "period_start", "period_end", "approval_status",
                      "submitted_total_hours", "approved_total_hours",
                      "calculated_total_hours", "payroll_hours_to_use"):
            val = r.get(field)
            if val is not None:
                text_parts.append(f"{field}: {val}")

        entries = r.get("entries") or []
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
            "text":       text,
            "text_chars": len(text),
            "tables":     0,
            "vlm_entries": entries,
            "vlm_meta":    {k: v for k, v in r.items() if k not in ("entries", "rejected_entries")},
            "raw_output":  r,
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

    raise HTTPException(400, f"Unknown parser '{parser}'.")


# ── Step 3: Run LLM extraction ─────────────────────────────────────────────────

@router.post("/lab/{session_id}/run-llm")
async def lab_run_llm(session_id: str, body: dict):
    """
    Extract timesheet data via LLM from parsed text.
    Body: { "text": "...", "parser_used": "pdfplumber" }
    """
    s    = _get_session(session_id)
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "No text provided. Run a parser in Step 2 first.")

    t0 = time.perf_counter()
    try:
        from app.services.llm_service import LLMService, EXTRACTION_PROMPT_TEMPLATE
        from app.core.config import settings

        if not settings.LLM_ENABLED:
            return {"status": "skipped", "note": "LLM_ENABLED=false", "entries": [], "summary": {}}

        try:
            prompt_preview = EXTRACTION_PROMPT_TEMPLATE.format(raw_text=text[:2000])
        except Exception:
            prompt_preview = text[:500]

        svc       = LLMService()
        extracted = svc.extract_timesheet_json(raw_text=text, file_metadata={"filename": s["filename"]})

        entries, employee_name = [], None
        if isinstance(extracted, dict):
            entries       = extracted.get("entries", [])
            employee_name = extracted.get("employee_name")
        elif isinstance(extracted, list):
            entries = extracted

        total_hours = 0.0; dates = []
        for e in entries:
            for hk in ("hours","regular_hours","total_hours"):
                try:
                    h = float(e.get(hk) or 0)
                    if h: total_hours += h; break
                except (TypeError, ValueError): pass
            d = e.get("date") or e.get("work_date")
            if d: dates.append(str(d))

        return {
            "session_id":     session_id,
            "parser_used":    body.get("parser_used","unknown"),
            "status":         "success",
            "duration_ms":    round((time.perf_counter()-t0)*1000),
            "provider":       settings.LLM_PROVIDER,
            "model":          getattr(settings,"OLLAMA_MODEL","unknown"),
            "prompt_preview": prompt_preview[:1200] + ("…" if len(prompt_preview)>1200 else ""),
            "employee_name":  employee_name,
            "entries":        entries,
            "summary": {
                "entries_found": len(entries),
                "total_hours":   round(total_hours, 2),
                "date_range":    f"{min(dates)} → {max(dates)}" if dates else "not detected",
                "unique_dates":  len(set(dates)),
            },
        }
    except HTTPException: raise
    except Exception as e:
        return {"session_id": session_id, "status": "error",
                "duration_ms": round((time.perf_counter()-t0)*1000),
                "error": str(e), "entries": [], "summary": {}}


# ── Session info ───────────────────────────────────────────────────────────────

@router.get("/lab/{session_id}/info")
async def lab_session_info(session_id: str):
    s = _get_session(session_id)
    return {"session_id": session_id, "filename": s["filename"],
            "ext": s["ext"], "size_kb": s["size_kb"],
            "available_parsers": _get_available_parsers(s["ext"])}

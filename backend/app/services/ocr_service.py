"""
OCR service — Phase 3.
Full multi-engine OCR: PaddleOCR (GPU-accelerated) → Tesseract → Docling OCR.
Used for scanned PDFs and image files.

After OCR, text is classified as TIMESHEET_CANDIDATE, NON_TIMESHEET_DOCUMENT, or
UNKNOWN_DOCUMENT_NEEDS_REVIEW and the result is stored in the file record.
"""
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UploadedFile, RawExtraction, FileProcessingLog, gen_uuid

logger = logging.getLogger(__name__)

# Keywords that strongly suggest this is a timesheet
_TIMESHEET_KEYWORDS = re.compile(
    r"\bhours?\b|\btime\s*sheet\b|\btimesheet\b|\bwork\s*date\b"
    r"|\bin\s*time\b|\bout\s*time\b|\bclock\s*in\b|\bclock\s*out\b"
    r"|\bregular\b|\bovertime\b|\bemployee\b|\bapproved\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w+\s+20\d{2}\b",
    re.IGNORECASE,
)

# Keywords that strongly suggest NON-timesheet content
_NON_TIMESHEET_KEYWORDS = re.compile(
    r"\binvoice\b|\breimburs\b|\breceipt\b|\bpurchase\s*order\b|\bstatement\b"
    r"|\bcheck\s*number\b|\bamount\s*due\b|\bpayment\s*terms\b",
    re.IGNORECASE,
)


def _classify_document(text: str) -> str:
    """Classify OCR'd text as TIMESHEET_CANDIDATE, NON_TIMESHEET_DOCUMENT, or UNKNOWN."""
    if not text or len(text.strip()) < 20:
        return "UNKNOWN_DOCUMENT_NEEDS_REVIEW"
    ts_hits = len(_TIMESHEET_KEYWORDS.findall(text))
    non_ts_hits = len(_NON_TIMESHEET_KEYWORDS.findall(text))
    if ts_hits >= 2 and ts_hits > non_ts_hits:
        return "TIMESHEET_CANDIDATE"
    if non_ts_hits >= 2 and non_ts_hits >= ts_hits:
        return "NON_TIMESHEET_DOCUMENT"
    if ts_hits >= 1:
        return "TIMESHEET_CANDIDATE"
    return "UNKNOWN_DOCUMENT_NEEDS_REVIEW"


class OCRService:
    def __init__(self, db: Session):
        self.db = db
        self._paddle = None
        self._paddle_init_attempted = False

    @staticmethod
    def _score_extraction(r: Dict[str, Any]) -> float:
        """Quality score for an engine's output — rewards real table structure
        and timesheet signal (dates) over loose text. Used to pick the best of
        the three image-based engines."""
        text = (r.get("raw_text") or "")
        if not text.strip():
            return 0.0
        tables = r.get("raw_tables") or []
        table_rows = sum(len(t.get("rows") or []) for t in tables)
        date_hits = len(re.findall(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", text))
        score = (
            table_rows * 2.0
            + date_hits * 1.0
            + min(len(text) / 500.0, 8.0)
            + float(r.get("confidence") or 0.0) * 3.0
        )
        return round(score, 2)

    def _run_three(self, path: str, ext: str) -> Dict[str, Dict[str, Any]]:
        """Run flat OCR, OCR+VLM fusion and VLM-only on a single pdf/image input."""
        engines: Dict[str, Dict[str, Any]] = {}

        # 1. Flat OCR (PaddleOCR/Tesseract) — accurate chars, no structure
        try:
            ocr = self._ocr_pdf(path) if ext == ".pdf" else self._ocr_image(path)
            engines["ocr"] = {
                "raw_text": ocr.get("raw_text") or "", "raw_tables": None,
                "confidence": ocr.get("confidence") or 0.0,
                "warnings": ocr.get("warnings") or [],
            }
        except Exception as exc:
            logger.warning("multi-engine: flat OCR failed: %s", exc)
            engines["ocr"] = {"raw_text": "", "raw_tables": None, "confidence": 0.0, "error": str(exc)}

        # 2. OCR + VLM fusion — OCR-grounded VLM rebuilds the table layout
        try:
            from app.services.ocr_vlm_fusion_service import OcrVlmFusionService
            fr = OcrVlmFusionService().process(
                path, ext, max_pages=getattr(settings, "OCR_MAX_PAGES", 25))
            engines["ocr_vlm"] = {
                "raw_text": fr.get("raw_text") or "", "raw_tables": fr.get("raw_tables"),
                "confidence": fr.get("confidence") or 0.0,
                "warnings": fr.get("warnings") or [],
            }
        except Exception as exc:
            logger.warning("multi-engine: fusion failed: %s", exc)
            engines["ocr_vlm"] = {"raw_text": "", "raw_tables": None, "confidence": 0.0, "error": str(exc)}

        # 3. VLM-only — vision model transcribes the page image directly
        try:
            from app.services.vlm_service import VLMService
            vlm = VLMService()
            vr = (vlm.read_text_from_pdf(path, max_pages=getattr(settings, "OCR_MAX_PAGES", 25))
                  if ext == ".pdf" else vlm.read_text_from_image(path, ext))
            vtext = vr.get("raw_text") or ""
            engines["vlm"] = {
                "raw_text": vtext, "raw_tables": None,
                "confidence": 0.7 if vtext.strip() else 0.0,
                "warnings": vr.get("errors") or [],
            }
        except Exception as exc:
            logger.warning("multi-engine: VLM failed: %s", exc)
            engines["vlm"] = {"raw_text": "", "raw_tables": None, "confidence": 0.0, "error": str(exc)}

        return engines

    @staticmethod
    def _merge_engines(per_image: List[Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        """Merge per-image engine results (multi-image DOCX) into one set per engine."""
        merged: Dict[str, Dict[str, Any]] = {}
        for key in ("ocr", "ocr_vlm", "vlm"):
            texts, tables, confs = [], [], []
            for img in per_image:
                e = img.get(key) or {}
                if e.get("raw_text"):
                    texts.append(e["raw_text"])
                if e.get("raw_tables"):
                    tables.extend(e["raw_tables"])
                confs.append(e.get("confidence") or 0.0)
            merged[key] = {
                "raw_text": "\n\n--- IMAGE BREAK ---\n\n".join(texts),
                "raw_tables": tables or None,
                "confidence": (sum(confs) / len(confs)) if confs else 0.0,
                "warnings": [],
            }
        return merged

    def _multi_engine(self, path: str, ext: str) -> Optional[Dict[str, Any]]:
        """Run flat OCR, OCR+VLM fusion, and VLM-only; score each; keep the best.

        Handles image-based files: scanned PDFs, images, and image-only DOCX
        (embedded images are extracted first, then each is run through the engines).
        """
        import shutil, tempfile

        cleanup_dir = None
        try:
            if ext in (".docx", ".doc"):
                from app.services.parsers.docx_parser import DocxParser
                cleanup_dir = tempfile.mkdtemp(prefix="docx_me_")
                imgs = DocxParser.extract_embedded_images(path, dest_dir=cleanup_dir)
                if not imgs:
                    logger.info("multi-engine: no embedded images in DOCX — falling back")
                    return None
                logger.info("multi-engine: DOCX has %d embedded image(s)", len(imgs))
                per_image = [self._run_three(ip, os.path.splitext(ip)[1].lower()) for ip in imgs]
                engines = self._merge_engines(per_image)
            else:
                engines = self._run_three(path, ext)
        finally:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

        scores = {k: self._score_extraction(v) for k, v in engines.items()}
        best_key = max(scores, key=lambda k: scores[k])
        best = engines[best_key]
        if not (best.get("raw_text") or "").strip():
            logger.info("multi-engine: all engines empty — falling back to flat OCR")
            return None

        score_summary = ", ".join(f"{k}={scores[k]}" for k in ("ocr", "ocr_vlm", "vlm"))
        logger.info("multi-engine: scores [%s] → best=%s", score_summary, best_key)

        return {
            "raw_text": best["raw_text"],
            "raw_tables": best.get("raw_tables"),
            "confidence": best.get("confidence") or 0.0,
            "method": f"multiengine:{best_key}",
            "warnings": (best.get("warnings") or []) + [f"multi-engine scores: {score_summary}"],
            "engine_results": {
                k: {"chars": len(v.get("raw_text") or ""),
                    "tables": len(v.get("raw_tables") or []),
                    "score": scores[k],
                    "error": v.get("error")}
                for k, v in engines.items()
            },
            "best_engine": best_key,
        }

    def _try_fusion(self, path: str, ext: str) -> Optional[Dict[str, Any]]:
        """Run OCR+VLM fusion; return a normalized result dict or None to fall back."""
        try:
            from app.services.ocr_vlm_fusion_service import OcrVlmFusionService
            fr = OcrVlmFusionService().process(
                path, ext, max_pages=getattr(settings, "OCR_MAX_PAGES", 25))
            if not (fr.get("raw_text") or "").strip():
                logger.info("fusion produced no text — falling back to flat OCR")
                return None
            return {
                "raw_text": fr.get("raw_text"),
                "raw_tables": fr.get("raw_tables"),
                "confidence": fr.get("confidence", 0.9),
                "method": "ocr_vlm_fusion",
                "warnings": fr.get("warnings", []),
            }
        except Exception as exc:
            logger.warning("fusion failed (%s) — falling back to flat OCR", exc)
            return None

    def process(self, file_record: UploadedFile, prior_result: Dict[str, Any]) -> Dict[str, Any]:
        """Run OCR on scanned PDF or image. Updates the RawExtraction record."""
        path = file_record.stored_file_path
        ext = (file_record.file_ext or "").lower()

        try:
            result = None
            # Multi-engine (default): run OCR, OCR+VLM fusion and VLM, keep best.
            if getattr(settings, "PIPELINE_MULTIENGINE_IMAGES", False):
                result = self._multi_engine(path, ext)
            # OCR + VLM fusion only (opt-in): grounds a VLM on OCR text to rebuild
            # table structure, and yields raw_tables the flat OCR path can't.
            elif getattr(settings, "PIPELINE_USE_FUSION", False):
                result = self._try_fusion(path, ext)

            if result is None:
                if ext == ".pdf":
                    result = self._ocr_pdf(path)
                else:
                    result = self._ocr_image(path)

            # Classify OCR'd document type
            doc_classification = _classify_document(result.get("raw_text") or "")
            result["document_type"] = doc_classification

            # Update or create raw extraction
            raw = (
                self.db.query(RawExtraction)
                .filter(RawExtraction.file_id == file_record.id)
                .first()
            )
            if raw:
                existing_text = raw.raw_text or ""
                ocr_text = result.get("raw_text") or ""
                raw.raw_text = f"{existing_text}\n\n[OCR]\n{ocr_text}".strip() if existing_text else ocr_text
                raw.confidence = result.get("confidence")
                raw.extraction_method = f"{raw.extraction_method}+{result.get('method', 'ocr')}"
                raw.extraction_warnings = (raw.extraction_warnings or []) + (result.get("warnings") or [])
                # Fusion produces real tables — keep them so the normalizer can map columns.
                if result.get("raw_tables"):
                    raw.raw_tables = result.get("raw_tables")
            else:
                raw = RawExtraction(
                    id=gen_uuid(),
                    file_id=file_record.id,
                    extraction_method=result.get("method", "ocr"),
                    raw_text=result.get("raw_text"),
                    raw_tables=result.get("raw_tables"),
                    confidence=result.get("confidence"),
                    extraction_warnings=result.get("warnings"),
                )
                self.db.add(raw)

            # Update file status and document classification
            if doc_classification == "NON_TIMESHEET_DOCUMENT":
                file_record.is_timesheet_candidate = False
                file_record.processing_status = "NON_TIMESHEET_DOCUMENT"
            else:
                file_record.processing_status = "PARSED"

            file_record.updated_at = datetime.utcnow()
            self._log(
                file_record.id, "OCR", "SUCCESS",
                f"OCR via {result.get('method')}, "
                f"confidence={result.get('confidence', 0):.2f}, "
                f"classification={doc_classification}",
            )
            self.db.commit()
            return result

        except Exception as e:
            logger.error(f"OCR failed for {file_record.file_name}: {e}", exc_info=True)
            file_record.processing_status = "NEEDS_REVIEW"
            file_record.updated_at = datetime.utcnow()
            self._log(file_record.id, "OCR", "FAILED", str(e))
            self.db.commit()
            return {"raw_text": None, "confidence": 0.0, "method": "failed", "warnings": [str(e)]}

    # ── PDF OCR ──────────────────────────────────────────────────────────────

    def _ocr_pdf(self, path: str) -> Dict[str, Any]:
        """Render each PDF page as image (up to MAX_OCR_PAGES), then OCR it."""
        max_pages = settings.OCR_MAX_PAGES
        dpi_threshold = settings.OCR_DPI_THRESHOLD_PAGES
        dpi_normal = settings.OCR_DPI_NORMAL
        dpi_high = settings.OCR_DPI_HIGH

        try:
            import fitz
            doc = fitz.open(path)
            total_pages = len(doc)
            pages_to_ocr = list(doc)[:max_pages]

            warnings: List[str] = []
            if total_pages > max_pages:
                msg = (
                    f"OCR_PAGE_LIMIT_REACHED: PDF has {total_pages} pages — "
                    f"only processing first {max_pages} to limit time: {os.path.basename(path)}"
                )
                logger.warning(msg)
                warnings.append(msg)

            all_text = []
            all_confidences = []
            dpi = dpi_high if total_pages <= dpi_threshold else dpi_normal

            for page_num, page in enumerate(pages_to_ocr):
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                    pix.save(tmp_path)

                try:
                    page_result = self._ocr_image(tmp_path)
                    page_text = page_result.get("raw_text", "") or ""
                    all_text.append(f"[Page {page_num + 1}]\n{page_text}")
                    if page_result.get("confidence"):
                        all_confidences.append(page_result["confidence"])
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

            doc.close()

            avg_conf = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
            if avg_conf < settings.OCR_CONFIDENCE_THRESHOLD:
                warnings.append(f"Low OCR confidence: {avg_conf:.2f}")

            return {
                "raw_text": "\n\n".join(all_text),
                "confidence": round(avg_conf, 4),
                "method": "pdf_ocr",
                "warnings": warnings,
            }
        except Exception as e:
            raise RuntimeError(f"PDF OCR failed: {e}") from e

    # ── Image OCR ─────────────────────────────────────────────────────────────

    def _ocr_image(self, path: str) -> Dict[str, Any]:
        """OCR a single image file.

        Strategy:
        - GPU available → PaddleOCR first (faster/more accurate), Tesseract fallback.
        - CPU only → Tesseract first (much faster on CPU), PaddleOCR as last resort.
        """
        use_paddle_first = settings.OCR_USE_GPU and settings.OCR_ENABLED

        if use_paddle_first:
            result = self._try_paddle(path)
            if result and result.get("confidence", 0) >= 0.3:
                return result

        # Tesseract: primary on CPU, fallback on GPU
        if settings.TESSERACT_ENABLED:
            result = self._try_tesseract(path)
            if result:
                return result

        # PaddleOCR CPU fallback only if Tesseract also failed
        if not use_paddle_first and settings.OCR_ENABLED:
            result = self._try_paddle(path)
            if result and result.get("confidence", 0) >= 0.3:
                return result

        raise RuntimeError(f"All OCR engines failed for {path}")

    def _try_paddle(self, path: str) -> Optional[Dict[str, Any]]:
        """PaddleOCR extraction with lazy init."""
        if not self._paddle_init_attempted:
            self._paddle_init_attempted = True
            try:
                from paddleocr import PaddleOCR
                self._paddle = PaddleOCR(
                    use_angle_cls=True,
                    lang="en",
                    use_gpu=settings.OCR_USE_GPU,
                    show_log=False,
                    enable_mkldnn=False,
                )
                logger.info(f"PaddleOCR initialized (GPU={settings.OCR_USE_GPU})")
            except Exception as e:
                logger.warning(f"PaddleOCR init failed: {e}")
                self._paddle = None

        if self._paddle is None:
            return None

        try:
            result = self._paddle.ocr(path, cls=True)
            if not result or not result[0]:
                return {"raw_text": "", "confidence": 0.0, "method": "paddleocr",
                        "warnings": ["Empty OCR result"]}

            lines = []
            scores = []
            for line in result[0]:
                if line and len(line) >= 2:
                    text, score = line[1]
                    lines.append(text)
                    scores.append(float(score))

            avg_conf = sum(scores) / len(scores) if scores else 0.0
            warnings = [] if avg_conf >= settings.OCR_CONFIDENCE_THRESHOLD else ["Low PaddleOCR confidence"]
            return {
                "raw_text": "\n".join(lines),
                "confidence": round(avg_conf, 4),
                "method": "paddleocr",
                "warnings": warnings,
            }
        except Exception as e:
            logger.warning(f"PaddleOCR inference failed: {e}")
            return None

    def _try_tesseract(self, path: str) -> Optional[Dict[str, Any]]:
        """Tesseract OCR — robust CPU fallback."""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(path)
            custom_config = "--oem 3 --psm 6"
            text = pytesseract.image_to_string(img, config=custom_config)

            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT,
                                             config=custom_config)
            scores = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
            avg_conf = (sum(scores) / len(scores) / 100) if scores else 0.0

            warnings = [] if avg_conf >= settings.OCR_CONFIDENCE_THRESHOLD else ["Low Tesseract confidence"]
            return {
                "raw_text": text.strip(),
                "confidence": round(avg_conf, 4),
                "method": "tesseract",
                "warnings": warnings,
            }
        except Exception as e:
            logger.warning(f"Tesseract failed: {e}")
            return None

    def _log(self, file_id: str, stage: str, status: str, message: str) -> None:
        log = FileProcessingLog(id=gen_uuid(), file_id=file_id,
                                stage=stage, status=status, message=message)
        self.db.add(log)
        self.db.commit()

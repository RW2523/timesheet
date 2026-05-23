"""
OCR service — Phase 3.
PaddleOCR → Docling → Tesseract fallback.
"""
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UploadedFile, RawExtraction, FileProcessingLog, gen_uuid

logger = logging.getLogger(__name__)


class OCRService:
    def __init__(self, db: Session):
        self.db = db
        self._paddle = None
        self._tesseract_available = settings.TESSERACT_ENABLED

    def process(self, file_record: UploadedFile, prior_result: Dict[str, Any]) -> Dict[str, Any]:
        """Run OCR on image or scanned PDF. Updates raw_extraction record."""
        path = file_record.stored_file_path
        ext = (file_record.file_ext or "").lower()

        try:
            if ext == ".pdf":
                result = self._ocr_pdf(path)
            else:
                result = self._ocr_image(path)

            # Update raw extraction
            raw = (
                self.db.query(RawExtraction)
                .filter(RawExtraction.file_id == file_record.id)
                .first()
            )
            if raw:
                raw.raw_text = result.get("raw_text")
                raw.confidence = result.get("confidence")
                raw.extraction_method = result.get("method", "ocr")
                raw.extraction_warnings = result.get("warnings")
            else:
                raw = RawExtraction(
                    id=gen_uuid(),
                    file_id=file_record.id,
                    extraction_method=result.get("method", "ocr"),
                    raw_text=result.get("raw_text"),
                    confidence=result.get("confidence"),
                    extraction_warnings=result.get("warnings"),
                )
                self.db.add(raw)

            file_record.processing_status = "PARSED"
            file_record.updated_at = datetime.utcnow()
            self._log(file_record.id, "OCR", "SUCCESS", f"OCR via {result.get('method')}")
            self.db.commit()
            return result

        except Exception as e:
            logger.error(f"OCR failed for {file_record.file_name}: {e}", exc_info=True)
            file_record.processing_status = "NEEDS_REVIEW"
            file_record.updated_at = datetime.utcnow()
            self._log(file_record.id, "OCR", "FAILED", str(e))
            self.db.commit()
            return {"raw_text": None, "confidence": 0.0, "method": "failed", "warnings": [str(e)]}

    def _ocr_image(self, path: str) -> Dict[str, Any]:
        """OCR a single image file."""
        # Try PaddleOCR first
        if settings.OCR_ENABLED:
            try:
                return self._paddle_ocr(path)
            except Exception as e:
                logger.warning(f"PaddleOCR failed: {e}")

        # Tesseract fallback
        if self._tesseract_available:
            try:
                return self._tesseract_ocr(path)
            except Exception as e:
                logger.warning(f"Tesseract failed: {e}")

        raise RuntimeError("All OCR methods failed for image")

    def _ocr_pdf(self, path: str) -> Dict[str, Any]:
        """OCR a scanned PDF by rendering pages to images."""
        try:
            import fitz
            from PIL import Image
            import io

            doc = fitz.open(path)
            all_text = []
            confidences = []

            for page_num, page in enumerate(doc):
                # Render at 200dpi
                mat = fitz.Matrix(200 / 72, 200 / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                tmp_path = f"/tmp/ocr_page_{page_num}.png"
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)

                try:
                    page_result = self._ocr_image(tmp_path)
                    all_text.append(page_result.get("raw_text", ""))
                    if page_result.get("confidence"):
                        confidences.append(page_result["confidence"])
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

            doc.close()
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            return {
                "raw_text": "\n\n--- Page Break ---\n\n".join(all_text),
                "confidence": avg_conf,
                "method": "pdf_ocr",
                "warnings": [],
            }
        except Exception as e:
            raise RuntimeError(f"PDF OCR failed: {e}") from e

    def _paddle_ocr(self, path: str) -> Dict[str, Any]:
        if self._paddle is None:
            from paddleocr import PaddleOCR
            self._paddle = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                use_gpu=settings.OCR_USE_GPU,
                show_log=False,
            )

        result = self._paddle.ocr(path, cls=True)
        if not result or not result[0]:
            return {"raw_text": "", "confidence": 0.0, "method": "paddleocr", "warnings": ["Empty OCR result"]}

        lines = []
        scores = []
        for line in result[0]:
            text, score = line[1]
            lines.append(text)
            scores.append(score)

        avg_conf = sum(scores) / len(scores) if scores else 0.0
        return {
            "raw_text": "\n".join(lines),
            "confidence": round(avg_conf, 4),
            "method": "paddleocr",
            "warnings": [] if avg_conf >= settings.OCR_CONFIDENCE_THRESHOLD else ["Low OCR confidence"],
        }

    def _tesseract_ocr(self, path: str) -> Dict[str, Any]:
        import pytesseract
        from PIL import Image

        img = Image.open(path)
        text = pytesseract.image_to_string(img, config="--psm 6")
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        scores = [int(c) for c in data["conf"] if str(c).isdigit() and int(c) >= 0]
        avg_conf = (sum(scores) / len(scores) / 100) if scores else 0.0

        return {
            "raw_text": text,
            "confidence": round(avg_conf, 4),
            "method": "tesseract",
            "warnings": [] if avg_conf >= settings.OCR_CONFIDENCE_THRESHOLD else ["Low OCR confidence"],
        }

    def _log(self, file_id: str, stage: str, status: str, message: str) -> None:
        log = FileProcessingLog(id=gen_uuid(), file_id=file_id, stage=stage, status=status, message=message)
        self.db.add(log)
        self.db.commit()

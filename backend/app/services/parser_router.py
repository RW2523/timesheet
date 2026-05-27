"""
Parser router — Phase 2.
Routes files to appropriate parsers based on extension.
Stores raw extraction result. All parsing errors are logged, never crash the pipeline.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.db.models import UploadedFile, RawExtraction, FileProcessingLog, gen_uuid
from app.core.config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif"}


class ParserRouter:
    def __init__(self, db: Session):
        self.db = db

    def route(self, file_record: UploadedFile) -> Optional[Dict[str, Any]]:
        """Route file to the correct parser and save raw extraction.

        Returns the parse result dict (may include ocr_required=True).
        Returns None only if there is no stored file path.
        """
        ext = (file_record.file_ext or "").lower()
        path = file_record.stored_file_path

        if not path:
            self._log(file_record.id, "PARSE", "FAILED", "No stored file path")
            return None

        # Skip noise / duplicate / unsupported without re-parsing
        if file_record.is_noise_file or file_record.is_duplicate:
            return None
        if not file_record.is_timesheet_candidate:
            return None

        try:
            if ext in (".xlsx", ".xls"):
                from app.services.parsers.excel_parser import ExcelParser
                result = ExcelParser().parse(path)
                parser_name = "excel"

            elif ext == ".csv":
                from app.services.parsers.csv_parser import CsvParser
                result = CsvParser().parse(path)
                parser_name = "csv"

            elif ext == ".docx":
                from app.services.parsers.docx_parser import DocxParser
                result = DocxParser().parse(path)
                parser_name = "docx"

            elif ext == ".pdf":
                from app.services.parsers.pdf_parser import PdfParser
                result = PdfParser().parse(path)
                parser_name = "pdf"

            elif ext in IMAGE_EXTENSIONS:
                # All image files go to OCR regardless of filename
                result = {
                    "ocr_required": True,
                    "raw_text": None,
                    "raw_tables": None,
                    "confidence": 0.0,
                    "warnings": [],
                    "extraction_method": "image_ocr_pending",
                }
                parser_name = "ocr_image"

            else:
                result = {
                    "ocr_required": False,
                    "raw_text": None,
                    "raw_tables": None,
                    "confidence": 0.0,
                    "warnings": [f"Unsupported extension: {ext}"],
                    "unsupported": True,
                }
                parser_name = "unsupported"

            # Persist raw extraction (upsert — avoid duplicates on reprocess)
            existing_raw = (
                self.db.query(RawExtraction)
                .filter(RawExtraction.file_id == file_record.id)
                .first()
            )
            if existing_raw:
                existing_raw.extraction_method = parser_name
                existing_raw.raw_text = result.get("raw_text")
                existing_raw.raw_tables = result.get("raw_tables")
                existing_raw.confidence = result.get("confidence")
                existing_raw.extraction_warnings = result.get("warnings")
            else:
                raw = RawExtraction(
                    id=gen_uuid(),
                    file_id=file_record.id,
                    extraction_method=parser_name,
                    raw_text=result.get("raw_text"),
                    raw_tables=result.get("raw_tables"),
                    confidence=result.get("confidence"),
                    extraction_warnings=result.get("warnings"),
                )
                self.db.add(raw)

            # Update file record
            file_record.parser_name = parser_name
            file_record.ocr_required = result.get("ocr_required", False)

            if result.get("unsupported"):
                file_record.processing_status = "UNSUPPORTED_FILE_TYPE"
            elif result.get("ocr_required"):
                file_record.processing_status = "OCR_REQUIRED"
            else:
                file_record.processing_status = "PARSED"

            file_record.updated_at = datetime.utcnow()
            self.db.commit()

            self._log(file_record.id, "PARSE", "SUCCESS",
                      f"Parsed with {parser_name}, ocr_required={result.get('ocr_required', False)}")
            return result

        except Exception as e:
            logger.error(f"Parse failed for {file_record.file_name}: {e}", exc_info=True)
            file_record.processing_status = "FAILED"
            file_record.updated_at = datetime.utcnow()
            self._log(file_record.id, "PARSE", "FAILED", str(e))
            self.db.commit()
            return None

    def _log(self, file_id: str, stage: str, status: str, message: str) -> None:
        log = FileProcessingLog(
            id=gen_uuid(), file_id=file_id, stage=stage,
            status=status, message=message,
        )
        self.db.add(log)
        self.db.commit()

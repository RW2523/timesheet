"""
Celery worker tasks — full processing pipeline.
Phases 1-9 are invoked in sequence per batch.
"""
import logging
import signal
from app.workers.celery_app import celery_app
from app.db.session import SessionLocal
from app.core.config import settings

logger = logging.getLogger(__name__)


class BatchCancelledError(Exception):
    pass


def _check_cancelled(db, batch_id: str) -> None:
    """Raise if the batch was cancelled while processing."""
    from app.db.models import BatchUpload
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if batch and batch.status == "CANCELLED":
        raise BatchCancelledError(f"Batch {batch_id} was cancelled")


@celery_app.task(bind=True, name="app.workers.tasks.process_batch", max_retries=3)
def process_batch(self, batch_id: str) -> dict:
    """
    Main pipeline entry point.
    Runs every phase for a batch in order:
      Phase 1: Safe unzip + file inventory
      Phase 2: Parser routing (Excel/CSV/DOCX/PDF)
      Phase 3: OCR for scanned PDFs and images
      Phase 4: JSON normalization (deterministic + optional LLM)
      Phase 5: Employee matching
      Phase 6: Timesheet entry creation + merging
      Phase 7: Validation engine
      Phase 8: Report generation
    """
    db = SessionLocal()
    try:
        from app.services.batch_service import BatchService
        from app.services.file_inventory_service import FileInventoryService
        from app.services.parser_router import ParserRouter
        from app.services.ocr_service import OCRService
        from app.services.normalizer import NormalizerService
        from app.services.employee_match_service import EmployeeMatchService
        from app.services.timesheet_service import TimesheetService
        from app.services.validation_service import ValidationService
        from app.services.report_service import ReportService

        batch_svc = BatchService(db)
        inventory_svc = FileInventoryService(db)
        parser = ParserRouter(db)
        ocr_svc = OCRService(db)
        normalizer = NormalizerService(db)
        matcher = EmployeeMatchService(db)
        timesheet_svc = TimesheetService(db)
        validator = ValidationService(db)
        report_svc = ReportService(db)

        # Phase 1 — unzip + inventory
        batch_svc.set_status(batch_id, "PROCESSING")
        zip_path = batch_svc.get_zip_path(batch_id)
        files = inventory_svc.build_inventory(batch_id, zip_path)
        logger.info(f"[{batch_id}] Inventory: {len(files)} files found")

        # Phase 2 & 3 — parse + OCR per file
        for file_record in files:
            _check_cancelled(db, batch_id)
            if file_record.is_noise_file or file_record.is_duplicate:
                continue
            try:
                raw = parser.route(file_record)
                if raw and raw.get("ocr_required"):
                    raw = ocr_svc.process(file_record, raw)
            except Exception as e:
                logger.warning(f"[{batch_id}] File {file_record.file_name} failed parse/OCR: {e}")
                inventory_svc.mark_failed(file_record.id, str(e))

        _check_cancelled(db, batch_id)

        # Phase 4 — normalize
        raw_extractions = inventory_svc.get_raw_extractions(batch_id)
        for raw_ext in raw_extractions:
            _check_cancelled(db, batch_id)
            try:
                normalizer.normalize(raw_ext)
            except Exception as e:
                logger.warning(f"[{batch_id}] Normalization failed for {raw_ext.file_id}: {e}")

        _check_cancelled(db, batch_id)

        # Phase 5 — employee matching
        file_records = inventory_svc.get_unmatched_files(batch_id)
        for file_record in file_records:
            _check_cancelled(db, batch_id)
            try:
                matcher.match_file(file_record)
            except Exception as e:
                logger.warning(f"[{batch_id}] Matching failed for {file_record.id}: {e}")

        _check_cancelled(db, batch_id)

        # Phase 6 — timesheet entries
        timesheet_svc.create_submissions_for_batch(batch_id)
        _check_cancelled(db, batch_id)

        # Phase 7 — validation
        validator.validate_batch(batch_id)
        _check_cancelled(db, batch_id)

        # Phase 8 — reports
        report_svc.generate_batch_report(batch_id)

        # Finalize
        batch_svc.finalize_batch(batch_id)
        return {"status": "completed", "batch_id": batch_id}

    except BatchCancelledError:
        logger.info(f"[{batch_id}] Batch was cancelled — stopping pipeline cleanly")
        return {"status": "cancelled", "batch_id": batch_id}
    except Exception as e:
        logger.error(f"[{batch_id}] Batch processing failed: {e}", exc_info=True)
        try:
            from app.services.batch_service import BatchService
            BatchService(db).set_status(batch_id, "FAILED")
        except Exception:
            pass
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.process_single_file")
def process_single_file(file_id: str, batch_id: str) -> dict:
    """Reprocess a single file (triggered from HR review UI)."""
    db = SessionLocal()
    try:
        from app.services.file_inventory_service import FileInventoryService
        from app.services.parser_router import ParserRouter
        from app.services.ocr_service import OCRService
        from app.services.normalizer import NormalizerService
        from app.services.employee_match_service import EmployeeMatchService

        inventory_svc = FileInventoryService(db)
        parser = ParserRouter(db)
        ocr_svc = OCRService(db)
        normalizer = NormalizerService(db)
        matcher = EmployeeMatchService(db)

        file_record = inventory_svc.get_file(file_id)
        raw = parser.route(file_record)
        if raw and raw.get("ocr_required"):
            raw = ocr_svc.process(file_record, raw)
        raw_ext = inventory_svc.get_raw_extraction_for_file(file_id)
        if raw_ext:
            normalizer.normalize(raw_ext)
        matcher.match_file(file_record)
        return {"status": "completed", "file_id": file_id}
    finally:
        db.close()

"""
Celery worker tasks — full processing pipeline.
Phases 1-9 are invoked in sequence per batch.
"""
import logging
from app.workers.celery_app import celery_app
from app.db.session import SessionLocal
from app.core.config import settings

logger = logging.getLogger(__name__)


class BatchCancelledError(Exception):
    pass


def _check_cancelled(db, batch_id: str) -> None:
    """Raise if the batch was cancelled while processing."""
    from app.db.models import BatchUpload
    db.expire_all()
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if batch and batch.status == "CANCELLED":
        raise BatchCancelledError(f"Batch {batch_id} was cancelled")


def _update_progress(db, batch_id: str, stage: str, current_file: str = None,
                     processed: int = None) -> None:
    """Write live progress into batch_uploads so the frontend can poll it."""
    from app.db.models import BatchUpload
    try:
        batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
        if batch:
            batch.current_stage = stage
            if current_file is not None:
                batch.current_file = current_file
            if processed is not None:
                batch.processed_files = processed
            db.commit()
    except Exception as exc:
        logger.debug(f"[{batch_id}] progress update failed (non-fatal): {exc}")
        db.rollback()


@celery_app.task(bind=True, name="app.workers.tasks.process_batch", max_retries=0)
def process_batch(self, batch_id: str) -> dict:
    """
    Main pipeline entry point.
      Phase 1: Safe unzip + file inventory
      Phase 2: Parser routing (Docling/Excel/CSV/DOCX/PDF)
      Phase 3: OCR for scanned PDFs and images
      Phase 4: JSON normalization (deterministic + LLM)
      Phase 5: Employee matching
      Phase 6: Timesheet entry creation
      Phase 7: Validation engine
      Phase 8: Report generation + final CSV
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
        _update_progress(db, batch_id, "Scanning files…")
        zip_path = batch_svc.get_zip_path(batch_id)
        files = inventory_svc.build_inventory(batch_id, zip_path)
        total = len(files)
        processable = [f for f in files if not f.is_noise_file and not f.is_duplicate]
        n = len(processable)
        logger.info(f"[{batch_id}] Phase 1 complete: {total} files, {n} to process")
        _update_progress(db, batch_id, f"Parsing files (0/{n})", processed=0)

        # Phase 2 & 3 — parse + OCR per file
        for idx, file_record in enumerate(processable, 1):
            _check_cancelled(db, batch_id)
            fname = file_record.file_name
            _update_progress(db, batch_id,
                             f"Parsing {idx}/{n} — {fname}",
                             current_file=fname,
                             processed=idx - 1)
            logger.info(f"[{batch_id}] Phase 2/3: {idx}/{n} — {fname}")
            try:
                raw = parser.route(file_record)
                if raw and raw.get("ocr_required"):
                    logger.info(f"[{batch_id}] Scanned PDF detected — running OCR on {fname}")
                    _update_progress(db, batch_id,
                                     f"OCR {idx}/{n} — {fname}",
                                     current_file=fname)
                    raw = ocr_svc.process(file_record, raw)
            except Exception as e:
                logger.warning(f"[{batch_id}] {fname} failed parse/OCR: {e}")
                # Clear the failed transaction before touching the session again,
                # otherwise this one file poisons the rest of the phase.
                db.rollback()
                inventory_svc.mark_failed(file_record.id, str(e))

        _check_cancelled(db, batch_id)
        _update_progress(db, batch_id, "Normalizing with AI…", processed=0)

        # Phase 4 — normalize (deterministic + LLM)
        raw_extractions = inventory_svc.get_raw_extractions(batch_id)
        total_norm = len(raw_extractions)
        logger.info(f"[{batch_id}] Phase 4: Normalizing {total_norm} extractions (LLM={'ON' if settings.LLM_ENABLED else 'OFF'})")
        for norm_idx, raw_ext in enumerate(raw_extractions, 1):
            _check_cancelled(db, batch_id)
            # Update stage every 5 items to reduce DB writes during heavy LLM phase
            if norm_idx % 5 == 1:
                _update_progress(db, batch_id,
                                 f"Normalizing {norm_idx}/{total_norm} (AI + LLM)",
                                 processed=norm_idx - 1)
            try:
                normalizer.normalize(raw_ext)
            except Exception as e:
                logger.warning(f"[{batch_id}] Normalization failed for {raw_ext.file_id}: {e}")
                db.rollback()

        _check_cancelled(db, batch_id)
        _update_progress(db, batch_id, "Matching employees…")

        # Phase 5 — employee matching
        file_records = inventory_svc.get_unmatched_files(batch_id)
        logger.info(f"[{batch_id}] Phase 5: Matching {len(file_records)} files to employees")
        for file_record in file_records:
            _check_cancelled(db, batch_id)
            try:
                matcher.match_file(file_record)
            except Exception as e:
                logger.warning(f"[{batch_id}] Matching failed for {file_record.id}: {e}")
                db.rollback()

        _check_cancelled(db, batch_id)
        _update_progress(db, batch_id, "Creating timesheet entries…")

        # Phase 6 — timesheet entries
        logger.info(f"[{batch_id}] Phase 6: Creating timesheet submissions")
        timesheet_svc.create_submissions_for_batch(batch_id)
        _check_cancelled(db, batch_id)
        _update_progress(db, batch_id, "Validating data…")

        # Phase 7 — validation
        logger.info(f"[{batch_id}] Phase 7: Running validation")
        validator.validate_batch(batch_id)
        _check_cancelled(db, batch_id)
        _update_progress(db, batch_id, "Generating reports & CSV…")

        # Phase 8 — reports + final summary CSV
        logger.info(f"[{batch_id}] Phase 8: Generating reports")
        report_svc.generate_batch_report(batch_id)
        report_svc.generate_summary_csv(batch_id)

        # Finalize
        _update_progress(db, batch_id, "Done", current_file=None)
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
        return {"status": "failed", "batch_id": batch_id, "error": str(e)}
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
        from app.services.timesheet_service import TimesheetService
        from app.services.validation_service import ValidationService
        from app.services.batch_service import BatchService

        inventory_svc = FileInventoryService(db)
        parser = ParserRouter(db)
        ocr_svc = OCRService(db)
        normalizer = NormalizerService(db)
        matcher = EmployeeMatchService(db)
        ts_svc = TimesheetService(db)
        val_svc = ValidationService(db)
        batch_svc = BatchService(db)

        file_record = inventory_svc.get_file(file_id)
        if not file_record:
            return {"status": "not_found", "file_id": file_id}

        # Stage 1 — Parse / OCR
        raw = parser.route(file_record)
        if raw and raw.get("ocr_required"):
            raw = ocr_svc.process(file_record, raw)

        # Stage 2 — Normalize
        raw_ext = inventory_svc.get_raw_extraction_for_file(file_id)
        if raw_ext:
            normalizer.normalize(raw_ext)

        # Stage 3 — Employee match
        matcher.match_file(file_record)

        # Stage 4 — Build timesheet entries (if matched)
        db.refresh(file_record)
        if file_record.match_status in ("AUTO_MATCHED", "MANUALLY_MATCHED"):
            ts_svc.create_submissions_for_batch(batch_id)

        # Stage 5 — Re-run validation for this batch
        if db.query(__import__('app.db.models', fromlist=['BatchUpload']).BatchUpload).filter_by(id=batch_id).first():
            val_svc.validate_batch(batch_id)
            batch_svc.finalize_batch(batch_id)

        return {"status": "completed", "file_id": file_id}
    except Exception as e:
        logger.error(f"process_single_file failed for {file_id}: {e}", exc_info=True)
        return {"status": "failed", "file_id": file_id, "error": str(e)}
    finally:
        db.close()


# ── Email crawl task ───────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="tasks.crawl_email_job", max_retries=2)
def crawl_email_job(self, job_id: str):
    """Run a single EmailCrawlJob: fetch → classify → save → create batch."""
    db = SessionLocal()
    try:
        from app.services.email_crawl_service import EmailCrawlService
        svc = EmailCrawlService(db)
        result = svc.run_crawl_job(job_id)
        return {
            "status": result.status,
            "job_id": job_id,
            "emails_scanned": result.emails_scanned,
            "emails_timesheet": result.emails_timesheet,
            "attachments_saved": result.attachments_saved,
            "batch_id": result.batch_id,
        }
    except Exception as e:
        logger.error(f"crawl_email_job failed: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
    finally:
        db.close()

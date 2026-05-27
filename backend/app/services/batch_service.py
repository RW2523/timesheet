"""Batch lifecycle service."""
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.models import BatchUpload, UploadedFile
from sqlalchemy import func

logger = logging.getLogger(__name__)


class BatchService:
    def __init__(self, db: Session):
        self.db = db

    def set_status(self, batch_id: str, status: str) -> None:
        batch = self.db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
        if batch:
            batch.status = status
            batch.updated_at = datetime.utcnow()
            self.db.commit()

    def get_zip_path(self, batch_id: str) -> str:
        batch = self.db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
        if not batch or not batch.original_file_path:
            raise FileNotFoundError(f"ZIP path not found for batch {batch_id}")
        return batch.original_file_path

    def finalize_batch(self, batch_id: str) -> None:
        """Recalculate counters and set final status.

        A batch is PAYROLL_READY only when:
          1. No files are stuck in FAILED or NEEDS_REVIEW/EXTRACTION_FAILED state, AND
          2. There are no open BLOCKER-level validation errors.
        """
        from app.db.models import TimesheetSubmission, ValidationError

        q = self.db.query(UploadedFile).filter(UploadedFile.batch_id == batch_id)
        total    = q.count()
        ignored  = q.filter(UploadedFile.is_noise_file == True).count()
        dups     = q.filter(UploadedFile.is_duplicate == True).count()
        processed = q.filter(
            UploadedFile.processing_status.in_(["COMPLETED", "MATCHED", "NORMALIZED"])
        ).count()
        failed = q.filter(UploadedFile.processing_status == "FAILED").count()
        review = q.filter(
            UploadedFile.processing_status.in_(["NEEDS_REVIEW", "EXTRACTION_FAILED"])
        ).count()

        payroll_ready = (
            self.db.query(func.count(TimesheetSubmission.id))
            .filter(
                TimesheetSubmission.batch_id == batch_id,
                TimesheetSubmission.payroll_status == "READY",
            )
            .scalar() or 0
        )

        # Count open validation blockers — these must all be resolved before payroll
        open_blockers = (
            self.db.query(func.count(ValidationError.id))
            .filter(
                ValidationError.batch_id == batch_id,
                ValidationError.status == "OPEN",
                ValidationError.severity == "BLOCKER",
            )
            .scalar() or 0
        )

        batch = self.db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
        if batch:
            batch.total_files = total
            batch.ignored_files = ignored
            batch.duplicate_files = dups
            batch.processed_files = processed
            batch.failed_files = failed
            batch.review_required_files = review
            batch.payroll_ready_count = payroll_ready
            needs_review = (failed > 0) or (review > 0) or (open_blockers > 0)
            batch.status = "NEEDS_REVIEW" if needs_review else "PAYROLL_READY"
            batch.updated_at = datetime.utcnow()
            self.db.commit()

        logger.info(
            f"Batch {batch_id} finalized: {total} total, {processed} processed, "
            f"{failed} failed, {review} review, {open_blockers} open blockers, "
            f"{payroll_ready} payroll-ready"
        )

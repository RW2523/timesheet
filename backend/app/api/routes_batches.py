"""Batch management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime

from app.db.session import get_db
from app.db.models import BatchUpload, ValidationError, UploadedFile
from app.schemas.batch import BatchSummary, BatchListResponse, DashboardStats

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStats)
def get_dashboard(db: Session = Depends(get_db)):
    total = db.query(func.count(BatchUpload.id)).scalar() or 0
    processing = db.query(func.count(BatchUpload.id)).filter(BatchUpload.status == "PROCESSING").scalar() or 0
    needs_review = db.query(func.count(BatchUpload.id)).filter(BatchUpload.status == "NEEDS_REVIEW").scalar() or 0
    payroll_ready = db.query(func.count(BatchUpload.id)).filter(BatchUpload.status == "PAYROLL_READY").scalar() or 0
    failed = db.query(func.count(BatchUpload.id)).filter(BatchUpload.status == "FAILED").scalar() or 0

    blockers = (
        db.query(func.count(ValidationError.id))
        .filter(ValidationError.severity == "BLOCKER", ValidationError.status == "OPEN")
        .scalar() or 0
    )
    warnings = (
        db.query(func.count(ValidationError.id))
        .filter(ValidationError.severity.in_(["WARNING", "ERROR"]), ValidationError.status == "OPEN")
        .scalar() or 0
    )

    return DashboardStats(
        total_batches=total,
        processing_batches=processing,
        needs_review_batches=needs_review,
        payroll_ready_batches=payroll_ready,
        failed_batches=failed,
        open_blockers=blockers,
        open_warnings=warnings,
    )


@router.get("/batches", response_model=BatchListResponse)
def list_batches(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(BatchUpload)
    if status:
        q = q.filter(BatchUpload.status == status)
    total = q.count()
    items = q.order_by(desc(BatchUpload.created_at)).offset(skip).limit(limit).all()
    return BatchListResponse(items=items, total=total)


@router.get("/batches/{batch_id}", response_model=BatchSummary)
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str, db: Session = Depends(get_db)):
    """
    Cancel a running or queued batch.
    Revokes the Celery task (SIGTERM), sets status to CANCELLED,
    and marks all DETECTED/QUEUED files as CANCELLED.
    """
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.status in ("PAYROLL_READY", "COMPLETED", "CANCELLED"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel a batch with status '{batch.status}'",
        )

    # Revoke Celery task
    task_id = (batch.summary_json or {}).get("celery_task_id")
    if task_id:
        try:
            from app.workers.celery_app import celery_app
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception as e:
            # Log but don't fail — still mark DB as cancelled
            import logging
            logging.getLogger(__name__).warning(f"Could not revoke Celery task {task_id}: {e}")

    # Mark batch cancelled
    batch.status = "CANCELLED"
    batch.summary_json = {**(batch.summary_json or {}), "cancelled_at": datetime.utcnow().isoformat()}
    batch.updated_at = datetime.utcnow()

    # Mark all in-progress files as cancelled too
    db.query(UploadedFile).filter(
        UploadedFile.batch_id == batch_id,
        UploadedFile.processing_status.in_(["DETECTED", "QUEUED", "PARSING", "OCR_PENDING", "NORMALIZING"]),
    ).update({"processing_status": "CANCELLED"}, synchronize_session=False)

    db.commit()

    return {"status": "cancelled", "batch_id": batch_id, "task_id": task_id}


@router.get("/batches/{batch_id}/status")
def get_batch_status(batch_id: str, db: Session = Depends(get_db)):
    """Lightweight status poll — used by frontend progress poller."""
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Count files by processing status
    from sqlalchemy import case
    counts = db.query(
        func.count(UploadedFile.id).label("total"),
        func.sum(case((UploadedFile.processing_status == "COMPLETED", 1), else_=0)).label("done"),
        func.sum(case((UploadedFile.processing_status == "FAILED", 1), else_=0)).label("failed"),
        func.sum(case((UploadedFile.processing_status == "NEEDS_REVIEW", 1), else_=0)).label("review"),
    ).filter(UploadedFile.batch_id == batch_id).first()

    return {
        "batch_id": batch_id,
        "status": batch.status,
        "total_files": counts.total or 0,
        "done_files": (counts.done or 0),
        "failed_files": counts.failed or 0,
        "review_files": counts.review or 0,
        "progress_pct": round(
            ((counts.done or 0) / max(counts.total or 1, 1)) * 100, 1
        ),
        "current_file": batch.current_file,
        "current_stage": batch.current_stage or "Processing…",
    }


@router.get("/batches/{batch_id}/stats")
def get_batch_stats(batch_id: str, db: Session = Depends(get_db)):
    """Return detailed file-level stats for the batch dashboard.

    Used by the frontend to display the secondary stats row in BatchSummaryCards.
    """
    from sqlalchemy import case
    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    stats = db.query(
        func.sum(case((UploadedFile.ocr_required == True, 1), else_=0)).label("ocr_files"),
        func.sum(case((UploadedFile.matched_employee_id.isnot(None), 1), else_=0)).label("matched_files"),
        func.sum(case(
            (UploadedFile.matched_employee_id.is_(None),
             case((UploadedFile.is_noise_file == False, case(
                (UploadedFile.is_duplicate == False, case(
                    (UploadedFile.is_timesheet_candidate == True, 1), else_=0
                )), else_=0
             )), else_=0)),
            else_=0,
        )).label("unmatched_files"),
        func.sum(case((UploadedFile.processing_status.in_(["EXTRACTION_FAILED", "FAILED"]), 1), else_=0)).label("extraction_failed"),
        func.sum(case((UploadedFile.processing_status == "NON_TIMESHEET_DOCUMENT", 1), else_=0)).label("non_timesheet"),
    ).filter(UploadedFile.batch_id == batch_id).first()

    return {
        "batch_id": batch_id,
        "ocr_files": stats.ocr_files or 0,
        "matched_files": stats.matched_files or 0,
        "unmatched_files": stats.unmatched_files or 0,
        "extraction_failed": stats.extraction_failed or 0,
        "non_timesheet": stats.non_timesheet or 0,
    }


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str, db: Session = Depends(get_db)):
    """Permanently delete a finished batch and all its related data.

    Only batches that are NOT actively processing can be deleted
    (statuses: NEEDS_REVIEW, PAYROLL_READY, COMPLETED, FAILED, CANCELLED).
    Also removes the original ZIP file from disk to free storage.
    """
    import os, shutil
    from app.db.models import (
        RawExtraction, TimesheetSubmission, TimesheetEntry,
        ValidationError as VE, GeneratedReport, EmployeeFileMatch, AuditLog,
    )

    batch = db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.status in ("UPLOADED", "PROCESSING"):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a batch that is currently processing. Stop it first.",
        )

    # ── Delete child rows in dependency order ──────────────────────────────
    file_ids = [
        r[0] for r in db.query(UploadedFile.id).filter(UploadedFile.batch_id == batch_id).all()
    ]
    sub_ids = [
        r[0] for r in db.query(TimesheetSubmission.id)
        .filter(TimesheetSubmission.batch_id == batch_id).all()
    ]

    # Timesheet entries
    if sub_ids:
        db.query(TimesheetEntry).filter(
            TimesheetEntry.submission_id.in_(sub_ids)
        ).delete(synchronize_session=False)

    # Validation errors
    db.query(VE).filter(VE.batch_id == batch_id).delete(synchronize_session=False)

    # Timesheet submissions
    db.query(TimesheetSubmission).filter(
        TimesheetSubmission.batch_id == batch_id
    ).delete(synchronize_session=False)

    # Raw extractions + employee file matches
    if file_ids:
        db.query(RawExtraction).filter(
            RawExtraction.file_id.in_(file_ids)
        ).delete(synchronize_session=False)
        db.query(EmployeeFileMatch).filter(
            EmployeeFileMatch.file_id.in_(file_ids)
        ).delete(synchronize_session=False)

    # Generated reports (DB rows + disk files)
    reports = db.query(GeneratedReport).filter(GeneratedReport.batch_id == batch_id).all()
    for rpt in reports:
        try:
            if rpt.file_path and os.path.exists(rpt.file_path):
                os.remove(rpt.file_path)
        except OSError:
            pass
    db.query(GeneratedReport).filter(
        GeneratedReport.batch_id == batch_id
    ).delete(synchronize_session=False)

    # Uploaded files
    db.query(UploadedFile).filter(
        UploadedFile.batch_id == batch_id
    ).delete(synchronize_session=False)

    # Audit logs
    db.query(AuditLog).filter(AuditLog.entity_id == batch_id).delete(synchronize_session=False)

    # ── Delete the batch record ────────────────────────────────────────────
    zip_path = batch.original_file_path
    db.delete(batch)
    db.commit()

    # ── Remove ZIP + extracted files from disk ─────────────────────────────
    deleted_files = 0
    if zip_path:
        upload_dir = os.path.dirname(zip_path)
        if os.path.isdir(upload_dir):
            try:
                shutil.rmtree(upload_dir)
                deleted_files += 1
            except OSError:
                pass

    return {"status": "deleted", "batch_id": batch_id, "disk_cleaned": deleted_files > 0}

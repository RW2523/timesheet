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
    }

"""Batch management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.db.session import get_db
from app.db.models import BatchUpload, ValidationError
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

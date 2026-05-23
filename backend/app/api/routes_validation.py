"""Validation errors endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime

from app.db.session import get_db
from app.db.models import ValidationError, gen_uuid
from app.schemas.validation import (
    ValidationErrorSchema, ValidationListResponse, ResolveValidationRequest
)

router = APIRouter()


@router.get("/batches/{batch_id}/validation", response_model=ValidationListResponse)
def list_validation_errors(
    batch_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    severity: str = Query(None),
    status: str = Query("OPEN"),
    db: Session = Depends(get_db),
):
    q = db.query(ValidationError).filter(ValidationError.batch_id == batch_id)
    if severity:
        q = q.filter(ValidationError.severity == severity)
    if status:
        q = q.filter(ValidationError.status == status)

    total = q.count()
    items = q.order_by(
        ValidationError.severity.desc(), desc(ValidationError.created_at)
    ).offset(skip).limit(limit).all()

    counts = (
        db.query(ValidationError.severity, func.count(ValidationError.id))
        .filter(ValidationError.batch_id == batch_id, ValidationError.status == "OPEN")
        .group_by(ValidationError.severity)
        .all()
    )
    count_map = dict(counts)

    return ValidationListResponse(
        items=items,
        total=total,
        blocker_count=count_map.get("BLOCKER", 0),
        error_count=count_map.get("ERROR", 0),
        warning_count=count_map.get("WARNING", 0),
        info_count=count_map.get("INFO", 0),
    )


@router.post("/validation/{error_id}/resolve")
def resolve_validation_error(
    error_id: str,
    body: ResolveValidationRequest,
    db: Session = Depends(get_db),
):
    err = db.query(ValidationError).filter(ValidationError.id == error_id).first()
    if not err:
        raise HTTPException(status_code=404, detail="Validation error not found")
    err.status = "RESOLVED"
    err.resolved_at = datetime.utcnow()
    db.commit()
    return {"status": "resolved", "id": error_id}

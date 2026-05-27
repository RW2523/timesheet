"""Validation errors endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime
from typing import Optional

from app.db.session import get_db
from app.db.models import ValidationError, UploadedFile, Employee, AuditLog, gen_uuid
from app.schemas.validation import (
    ValidationErrorSchema, ValidationListResponse, ResolveValidationRequest
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Rules that are batch-level admin warnings — excluded from per-batch HR view by default
ADMIN_ONLY_RULES = {"TWO_MONTH_INACTIVE"}


@router.get("/batches/{batch_id}/validation", response_model=ValidationListResponse)
def list_validation_errors(
    batch_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    severity: str = Query(None),
    status: str = Query("OPEN"),
    include_admin_rules: bool = Query(False, description="Include admin-only rules like TWO_MONTH_INACTIVE"),
    db: Session = Depends(get_db),
):
    q = db.query(ValidationError).filter(ValidationError.batch_id == batch_id)
    if severity:
        q = q.filter(ValidationError.severity == severity)
    if status:
        q = q.filter(ValidationError.status == status)
    if not include_admin_rules:
        q = q.filter(~ValidationError.rule_code.in_(ADMIN_ONLY_RULES))

    total = q.count()
    items = q.order_by(
        ValidationError.severity.desc(), desc(ValidationError.created_at)
    ).offset(skip).limit(limit).all()

    # Counts always exclude admin-only rules so badge numbers match what HR sees
    counts = (
        db.query(ValidationError.severity, func.count(ValidationError.id))
        .filter(
            ValidationError.batch_id == batch_id,
            ValidationError.status == "OPEN",
            ~ValidationError.rule_code.in_(ADMIN_ONLY_RULES),
        )
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

    # If a correction was provided, apply it before marking resolved
    if body.correction:
        _apply_correction(err, body.correction, db)

    err.status = "RESOLVED"
    err.resolved_at = datetime.utcnow()

    # Build resolution note with reviewer attribution
    reviewer = body.resolved_by_name or "HR"
    note_parts = [f"[RESOLVED by {reviewer}]"]
    if body.resolution_note:
        note_parts.append(body.resolution_note)
    err.action_required = " ".join(note_parts)

    # Write audit log (actor_user_id nullable — no auth system yet)
    audit = AuditLog(
        id=gen_uuid(),
        entity_type="validation_error",
        entity_id=error_id,
        action="RESOLVE",
        before_json={"status": "OPEN", "rule_code": err.rule_code},
        after_json={
            "status": "RESOLVED",
            "resolved_by_name": reviewer,
            "note": body.resolution_note,
        },
        created_at=datetime.utcnow(),
    )
    db.add(audit)
    db.commit()

    # Re-evaluate batch status — if this was the last open blocker the batch
    # should flip to PAYROLL_READY automatically.
    try:
        from app.services.batch_service import BatchService
        BatchService(db).finalize_batch(err.batch_id)
    except Exception as exc:
        logger.warning(f"finalize_batch after resolve failed: {exc}")

    return {"status": "resolved", "id": error_id, "resolved_by": reviewer}


def _apply_correction(err: ValidationError, correction, db: Session) -> None:
    """Apply human-supplied corrections to the underlying data.

    `correction` is a CorrectionPayload Pydantic model — use attribute access.
    """
    employee_name = correction.employee_name
    employee_id = correction.employee_id
    hours = correction.hours
    work_date = correction.date

    # Correct detected employee name on the file
    if err.file_id and employee_name:
        f = db.query(UploadedFile).filter(UploadedFile.id == err.file_id).first()
        if f:
            f.detected_employee_name = employee_name
            # If they also supplied an employee_id, create a MANUALLY_MATCHED record
            if employee_id:
                from app.db.models import EmployeeFileMatch
                f.matched_employee_id = employee_id
                f.match_status = "MANUALLY_MATCHED"
                f.match_confidence = 1.0
                match = EmployeeFileMatch(
                    id=gen_uuid(),
                    file_id=str(err.file_id),
                    detected_name=employee_name,
                    matched_employee_id=employee_id,
                    match_method="MANUAL",
                    match_confidence=1.0,
                    review_status="MANUAL",
                    reviewed_at=datetime.utcnow(),
                )
                db.add(match)
            f.updated_at = datetime.utcnow()

    # Correct timesheet entry hours / date
    if err.entry_id and (hours is not None or work_date):
        from app.db.models import TimesheetEntry
        entry = db.query(TimesheetEntry).filter(TimesheetEntry.id == err.entry_id).first()
        if entry:
            if hours is not None:
                try:
                    entry.entered_hours = float(hours)
                except (TypeError, ValueError):
                    pass
            if work_date:
                from datetime import date as dt_date
                try:
                    entry.work_date = dt_date.fromisoformat(work_date)
                except ValueError:
                    pass
            entry.updated_at = datetime.utcnow()


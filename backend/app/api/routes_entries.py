"""Timesheet entries endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from app.db.session import get_db
from app.db.models import TimesheetEntry, AuditLog, gen_uuid
from app.schemas.timesheet import TimesheetEntrySchema, EntryListResponse, EntryUpdateRequest

router = APIRouter()


@router.get("/batches/{batch_id}/entries", response_model=EntryListResponse)
def list_entries(
    batch_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    employee_id: str = Query(None),
    db: Session = Depends(get_db),
):
    from app.db.models import TimesheetSubmission
    q = (
        db.query(TimesheetEntry)
        .join(TimesheetSubmission, TimesheetEntry.submission_id == TimesheetSubmission.id)
        .filter(TimesheetSubmission.batch_id == batch_id)
    )
    if employee_id:
        q = q.filter(TimesheetEntry.employee_id == employee_id)
    total = q.count()
    items = q.order_by(TimesheetEntry.employee_id, TimesheetEntry.work_date).offset(skip).limit(limit).all()
    return EntryListResponse(items=items, total=total)


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: str,
    body: EntryUpdateRequest,
    db: Session = Depends(get_db),
):
    entry = db.query(TimesheetEntry).filter(TimesheetEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    before = {
        "entered_hours": str(entry.entered_hours),
        "in_time": str(entry.in_time),
        "out_time": str(entry.out_time),
    }

    if body.entered_hours is not None:
        entry.entered_hours = body.entered_hours
    if body.in_time is not None:
        entry.in_time = body.in_time
    if body.out_time is not None:
        entry.out_time = body.out_time
    if body.break_minutes is not None:
        entry.break_minutes = body.break_minutes
    if body.entry_type is not None:
        entry.entry_type = body.entry_type
    if body.leave_type is not None:
        entry.leave_type = body.leave_type

    entry.validation_status = "PENDING"
    entry.updated_at = datetime.utcnow()

    audit = AuditLog(
        id=gen_uuid(),
        entity_type="TimesheetEntry",
        entity_id=entry_id,
        action="MANUAL_EDIT",
        before_json=before,
        after_json={"override_reason": body.override_reason},
        created_at=datetime.utcnow(),
    )
    db.add(audit)
    db.commit()
    return TimesheetEntrySchema.model_validate(entry)

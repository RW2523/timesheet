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


@router.get("/batches/{batch_id}/timesheets")
def list_timesheets(batch_id: str, db: Session = Depends(get_db)):
    """Per-submission timesheets with day-level hours — powers the calendar view.

    Returns one entry per processed file (matched or not), each with its
    extracted/known employee name, period, monthly total and day records.
    """
    from app.db.models import TimesheetSubmission, Employee, UploadedFile

    subs = (
        db.query(TimesheetSubmission)
        .filter(TimesheetSubmission.batch_id == batch_id)
        .all()
    )
    out = []
    for s in subs:
        emp = db.query(Employee).filter(Employee.id == s.employee_id).first() if s.employee_id else None
        fname = None
        if s.file_id:
            uf = db.query(UploadedFile).filter(UploadedFile.id == s.file_id).first()
            fname = uf.file_name if uf else None

        entries = (
            db.query(TimesheetEntry)
            .filter(TimesheetEntry.submission_id == s.id)
            .order_by(TimesheetEntry.work_date)
            .all()
        )
        days = []
        total = 0.0
        for e in entries:
            reg = float(e.regular_hours or 0)
            ot = float(e.overtime_hours or 0)
            hrs = reg + ot
            if hrs == 0:
                hrs = float(e.calculated_hours or e.entered_hours or 0)
            total += hrs
            days.append({
                "date": e.work_date.isoformat() if e.work_date else None,
                "day_of_week": e.day_of_week,
                "hours": round(hrs, 2),
                "regular_hours": reg,
                "overtime_hours": ot,
                "entry_type": e.entry_type,
                "leave_type": e.leave_type,
                "in_time": str(e.in_time) if e.in_time else None,
                "out_time": str(e.out_time) if e.out_time else None,
                "break_minutes": e.break_minutes,
            })
        out.append({
            "submission_id": s.id,
            "file_id": s.file_id,
            "file_name": fname,
            "employee_name": (emp.full_name if emp else None) or s.detected_employee_name or "Unknown",
            "matched": bool(s.employee_id),
            "period_start": s.timesheet_start_date.isoformat() if s.timesheet_start_date else None,
            "period_end": s.timesheet_end_date.isoformat() if s.timesheet_end_date else None,
            "total_hours": round(total, 2),
            "approval_status": s.approval_status,
            "entries": days,
        })
    out.sort(key=lambda t: (t["employee_name"] or "z").lower())

    # "What is missing": candidate files that produced NO timesheet (extraction gap).
    sub_file_ids = {s.file_id for s in subs if s.file_id}
    candidates = (
        db.query(UploadedFile)
        .filter(
            UploadedFile.batch_id == batch_id,
            UploadedFile.is_noise_file == False,
            UploadedFile.is_duplicate == False,
            UploadedFile.is_timesheet_candidate == True,
        )
        .all()
    )
    missing_files = [
        {"file_id": f.id, "file_name": f.file_name,
         "status": f.processing_status, "ext": f.file_ext}
        for f in candidates if f.id not in sub_file_ids
    ]
    return {
        "batch_id": batch_id,
        "timesheets": out,
        "count": len(out),
        "missing_files": missing_files,
        "missing_count": len(missing_files),
    }


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

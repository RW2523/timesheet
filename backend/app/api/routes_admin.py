"""Admin endpoints for master data management."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import date
import os, shutil

from app.db.session import get_db
from app.db.models import (
    Employee, Vendor, ClientManager, EmployeeRate, HolidayCalendar, HolidayDate,
    PayrollPeriod, gen_uuid, BatchUpload, UploadedFile, RawExtraction,
    EmployeeFileMatch, TimesheetSubmission, TimesheetEntry, ValidationError,
    ApprovalRecord, GeneratedReport, AuditLog, FileProcessingLog,
    PayrollRun, PayrollResult, NotificationLog,
)

router = APIRouter()


# ── Employees ──────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    employee_code: Optional[str] = None
    vendor_id: Optional[str] = None
    employee_type: Optional[str] = "CONTRACTOR"
    is_active: Optional[bool] = True


@router.get("/admin/employees")
def list_employees(db: Session = Depends(get_db)):
    employees = db.query(Employee).filter(Employee.is_active == True).all()
    return {"items": [{"id": e.id, "full_name": e.full_name, "email": e.email, "employee_type": e.employee_type, "vendor_id": e.vendor_id} for e in employees], "total": len(employees)}


@router.post("/admin/employees")
def create_employee(body: EmployeeCreate, db: Session = Depends(get_db)):
    emp = Employee(id=gen_uuid(), **body.model_dump())
    db.add(emp)
    db.commit()
    return {"id": emp.id, "full_name": emp.full_name}


# ── Vendors ────────────────────────────────────────────────────────────────────

class VendorCreate(BaseModel):
    name: str
    overtime_enabled: bool = False
    regular_daily_limit: float = 8.0
    regular_weekly_limit: float = 40.0


@router.get("/admin/vendors")
def list_vendors(db: Session = Depends(get_db)):
    vendors = db.query(Vendor).all()
    return {"items": [{"id": v.id, "name": v.name, "overtime_enabled": v.overtime_enabled} for v in vendors], "total": len(vendors)}


@router.post("/admin/vendors")
def create_vendor(body: VendorCreate, db: Session = Depends(get_db)):
    v = Vendor(id=gen_uuid(), **body.model_dump())
    db.add(v)
    db.commit()
    return {"id": v.id, "name": v.name}


# ── Employee Rates ─────────────────────────────────────────────────────────────

class RateCreate(BaseModel):
    employee_id: str
    regular_rate: float
    overtime_rate: Optional[float] = None
    currency: str = "USD"
    effective_start_date: date
    effective_end_date: Optional[date] = None


@router.post("/admin/rates")
def create_rate(body: RateCreate, db: Session = Depends(get_db)):
    rate = EmployeeRate(id=gen_uuid(), **body.model_dump())
    db.add(rate)
    db.commit()
    return {"id": rate.id}


# ── Payroll Periods ────────────────────────────────────────────────────────────

class PayrollPeriodCreate(BaseModel):
    period_key: str
    start_date: date
    end_date: date
    cutoff_date: date
    payroll_run_date: Optional[date] = None


@router.get("/admin/payroll-periods")
def list_periods(db: Session = Depends(get_db)):
    periods = db.query(PayrollPeriod).order_by(PayrollPeriod.start_date.desc()).all()
    return {"items": [{"id": p.id, "period_key": p.period_key, "start_date": str(p.start_date), "end_date": str(p.end_date), "status": p.status} for p in periods], "total": len(periods)}


@router.post("/admin/payroll-periods")
def create_period(body: PayrollPeriodCreate, db: Session = Depends(get_db)):
    p = PayrollPeriod(id=gen_uuid(), **body.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id, "period_key": p.period_key}


# ── Holiday Calendars ──────────────────────────────────────────────────────────

class HolidayDateCreate(BaseModel):
    calendar_id: str
    holiday_date: date
    holiday_name: str
    paid_hours: float = 8.0


@router.get("/admin/holidays/{calendar_id}")
def list_holidays(calendar_id: str, db: Session = Depends(get_db)):
    dates = db.query(HolidayDate).filter(HolidayDate.calendar_id == calendar_id).order_by(HolidayDate.holiday_date).all()
    return {"items": [{"id": d.id, "holiday_date": str(d.holiday_date), "holiday_name": d.holiday_name, "paid_hours": float(d.paid_hours)} for d in dates]}


@router.post("/admin/holidays")
def create_holiday(body: HolidayDateCreate, db: Session = Depends(get_db)):
    h = HolidayDate(id=gen_uuid(), **body.model_dump())
    db.add(h)
    db.commit()
    return {"id": h.id}


# ── Inactivity Report ──────────────────────────────────────────────────────────

@router.get("/admin/inactive-employees")
def get_inactive_employees(db: Session = Depends(get_db)):
    """Return employees with no timesheet submission in the last 2 months.

    Only meaningful when the system has data spanning 2+ calendar months.
    Returns both the inactive employees list and whether the report is ready.
    """
    from dateutil.relativedelta import relativedelta
    from sqlalchemy import func, cast, String
    from datetime import datetime
    from app.db.models import TimesheetSubmission, Employee as Emp
    from app.core.config import settings

    # Check if we have enough history — count distinct (year, month) pairs
    distinct_months = (
        db.query(
            func.count(
                func.distinct(
                    func.concat(
                        cast(func.extract("year", TimesheetSubmission.timesheet_end_date), String),
                        "-",
                        cast(func.extract("month", TimesheetSubmission.timesheet_end_date), String),
                    )
                )
            )
        )
        .filter(TimesheetSubmission.timesheet_end_date.isnot(None))
        .scalar()
    ) or 0

    threshold = getattr(settings, "INACTIVE_MONTHS_THRESHOLD", 2)
    cutoff = datetime.utcnow() - relativedelta(months=threshold)

    if int(distinct_months) < 2:
        return {
            "ready": False,
            "reason": f"Only {distinct_months} month(s) of data available. Need at least 2 months to generate inactivity report.",
            "items": [],
            "total": 0,
        }

    employees = db.query(Emp).filter(Emp.is_active == True).all()  # noqa: E712
    inactive = []
    for emp in employees:
        last_sub = (
            db.query(TimesheetSubmission.timesheet_end_date)
            .filter(TimesheetSubmission.employee_id == emp.id)
            .order_by(TimesheetSubmission.timesheet_end_date.desc())
            .first()
        )
        last_date = last_sub[0] if last_sub else None
        if last_date:
            from datetime import datetime as dt2, time as dt_time
            last_date_dt = dt2.combine(last_date, dt_time.min)
        else:
            last_date_dt = None

        if last_date_dt is None or last_date_dt < cutoff:
            months_inactive = None
            if last_date_dt:
                delta = relativedelta(datetime.utcnow(), last_date_dt)
                months_inactive = delta.months + delta.years * 12

            inactive.append({
                "employee_id": emp.id,
                "full_name": emp.full_name,
                "email": emp.email,
                "last_submission": str(last_date) if last_date else None,
                "months_inactive": months_inactive,
                "never_submitted": last_date is None,
            })

    return {
        "ready": True,
        "total_active_employees": len(employees),
        "items": inactive,
        "total": len(inactive),
        "threshold_months": threshold,
        "cutoff_date": cutoff.date().isoformat(),
    }


# ── Danger Zone: Data Clearing ─────────────────────────────────────────────────

def _delete_batch_tree(db: Session) -> dict:
    """Delete all transactional/batch data. Keep master data (employees, vendors, periods, rates)."""
    from app.core.config import settings

    # Collect report files to remove from disk
    reports = db.query(GeneratedReport).all()
    disk_files_removed = 0
    for r in reports:
        if r.file_path and os.path.exists(r.file_path):
            try:
                os.remove(r.file_path)
                disk_files_removed += 1
            except OSError:
                pass

    # Remove upload directories for all batches
    batches = db.query(BatchUpload).all()
    dirs_removed = 0
    for b in batches:
        if b.original_file_path:
            upload_dir = os.path.dirname(b.original_file_path)
            if os.path.isdir(upload_dir):
                try:
                    shutil.rmtree(upload_dir)
                    dirs_removed += 1
                except OSError:
                    pass

    # Delete in FK-safe dependency order
    deleted = {}
    # 1. Leaf records — reference entries/submissions/files but nothing references them
    deleted["approval_records"] = db.query(ApprovalRecord).delete(synchronize_session=False)
    deleted["validation_errors"] = db.query(ValidationError).delete(synchronize_session=False)
    deleted["payroll_results"] = db.query(PayrollResult).delete(synchronize_session=False)
    deleted["notification_logs"] = db.query(NotificationLog).delete(synchronize_session=False)
    # 2. Entries (reference submissions)
    deleted["timesheet_entries"] = db.query(TimesheetEntry).delete(synchronize_session=False)
    # 3. Submissions
    deleted["timesheet_submissions"] = db.query(TimesheetSubmission).delete(synchronize_session=False)
    # 4. Payroll runs (reference payroll_periods only — safe after results gone)
    deleted["payroll_runs"] = db.query(PayrollRun).delete(synchronize_session=False)
    # 5. File-level records (all reference uploaded_files)
    deleted["employee_file_matches"] = db.query(EmployeeFileMatch).delete(synchronize_session=False)
    deleted["raw_extractions"] = db.query(RawExtraction).delete(synchronize_session=False)
    deleted["file_processing_logs"] = db.query(FileProcessingLog).delete(synchronize_session=False)
    deleted["generated_reports"] = db.query(GeneratedReport).delete(synchronize_session=False)
    # 6. Files then batches
    deleted["uploaded_files"] = db.query(UploadedFile).delete(synchronize_session=False)
    deleted["audit_logs"] = db.query(AuditLog).delete(synchronize_session=False)
    deleted["batches"] = db.query(BatchUpload).delete(synchronize_session=False)
    db.commit()

    return {
        **deleted,
        "disk_report_files_removed": disk_files_removed,
        "upload_dirs_removed": dirs_removed,
    }


@router.delete("/admin/clear-batch-data")
def clear_batch_data(
    confirm: str = Query(..., description="Must be 'CONFIRM' to proceed"),
    db: Session = Depends(get_db),
):
    """Delete all batch / processing data. Master data (employees, vendors, payroll periods) is preserved."""
    if confirm != "CONFIRM":
        raise HTTPException(status_code=400, detail="Pass confirm=CONFIRM to proceed")
    stats = _delete_batch_tree(db)
    return {"status": "cleared", "master_data_preserved": True, **stats}


@router.delete("/admin/clear-all-data")
def clear_all_data(
    confirm: str = Query(..., description="Must be 'DELETE_EVERYTHING' to proceed"),
    db: Session = Depends(get_db),
):
    """Delete ALL data including master data (employees, vendors, rates, periods). Irreversible."""
    if confirm != "DELETE_EVERYTHING":
        raise HTTPException(status_code=400, detail="Pass confirm=DELETE_EVERYTHING to proceed")

    stats = _delete_batch_tree(db)

    # Now also wipe master data
    stats["employee_rates"] = db.query(EmployeeRate).delete(synchronize_session=False)
    stats["holiday_dates"] = db.query(HolidayDate).delete(synchronize_session=False)
    stats["holiday_calendars"] = db.query(HolidayCalendar).delete(synchronize_session=False)
    stats["payroll_periods"] = db.query(PayrollPeriod).delete(synchronize_session=False)
    stats["vendors"] = db.query(Vendor).delete(synchronize_session=False)
    stats["employees"] = db.query(Employee).delete(synchronize_session=False)
    db.commit()

    return {"status": "all_data_cleared", "master_data_preserved": False, **stats}

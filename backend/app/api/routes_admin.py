"""Admin endpoints for master data management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import date

from app.db.session import get_db
from app.db.models import Employee, Vendor, ClientManager, EmployeeRate, HolidayCalendar, HolidayDate, PayrollPeriod, gen_uuid

router = APIRouter()


# ── Employees ──────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    employee_code: Optional[str] = None
    vendor_id: Optional[str] = None
    employee_type: Optional[str] = "CONTRACTOR"


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

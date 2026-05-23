"""Pydantic schemas for reports and payroll."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ReportSchema(BaseModel):
    id: str
    batch_id: Optional[str]
    payroll_run_id: Optional[str]
    report_type: str
    file_name: str
    generated_by: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportListResponse(BaseModel):
    items: list[ReportSchema]


class PayrollRunSchema(BaseModel):
    id: str
    payroll_period_id: str
    run_status: str
    total_employees: int
    payroll_ready_employees: int
    blocked_employees: int
    total_regular_hours: float
    total_overtime_hours: float
    total_regular_pay: float
    total_overtime_pay: float
    total_pay: float
    created_at: datetime

    model_config = {"from_attributes": True}


class PayrollResultSchema(BaseModel):
    id: str
    payroll_run_id: str
    employee_id: str
    vendor_id: Optional[str]
    regular_hours: float
    overtime_hours: float
    leave_days: float
    holiday_hours: float
    regular_rate: Optional[float]
    overtime_rate: Optional[float]
    regular_pay: float
    overtime_pay: float
    total_pay: float
    payroll_status: str
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}

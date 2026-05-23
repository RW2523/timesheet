"""Pydantic schemas for timesheet entries and submissions."""
from __future__ import annotations
from datetime import datetime, date, time
from typing import Optional, Any
from pydantic import BaseModel


class TimesheetEntrySchema(BaseModel):
    id: str
    submission_id: str
    employee_id: str
    work_date: date
    day_of_week: Optional[str]
    in_time: Optional[time]
    out_time: Optional[time]
    break_minutes: int
    entered_hours: Optional[float]
    calculated_hours: Optional[float]
    regular_hours: float
    overtime_hours: float
    entry_type: str
    leave_type: Optional[str]
    is_holiday: bool
    holiday_name: Optional[str]
    validation_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class EntryListResponse(BaseModel):
    items: list[TimesheetEntrySchema]
    total: int


class EntryUpdateRequest(BaseModel):
    entered_hours: Optional[float] = None
    in_time: Optional[time] = None
    out_time: Optional[time] = None
    break_minutes: Optional[int] = None
    entry_type: Optional[str] = None
    leave_type: Optional[str] = None
    override_reason: str


class TimesheetSubmissionSchema(BaseModel):
    id: str
    batch_id: Optional[str]
    file_id: Optional[str]
    employee_id: Optional[str]
    payroll_period_id: Optional[str]
    source_type: str
    submission_date: Optional[datetime]
    timesheet_start_date: Optional[date]
    timesheet_end_date: Optional[date]
    approval_status: str
    validation_status: str
    payroll_status: str
    is_late: bool
    created_at: datetime

    model_config = {"from_attributes": True}

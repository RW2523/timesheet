"""Pydantic schemas for validation errors."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel


class ValidationErrorSchema(BaseModel):
    id: str
    batch_id: Optional[str]
    file_id: Optional[str]
    submission_id: Optional[str]
    entry_id: Optional[str]
    employee_id: Optional[str]
    rule_code: str
    severity: str
    message: str
    expected_value: Optional[str]
    actual_value: Optional[str]
    action_required: Optional[str]
    assigned_to_role: Optional[str]
    status: str
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ValidationListResponse(BaseModel):
    items: list[ValidationErrorSchema]
    total: int
    blocker_count: int
    error_count: int
    warning_count: int
    info_count: int


class CorrectionPayload(BaseModel):
    """Fields the HR reviewer can fill in to fix the underlying data."""
    employee_name: Optional[str] = None   # correct the detected name
    employee_id: Optional[str] = None     # assign a specific employee
    hours: Optional[float] = None         # fix hours on an entry
    date: Optional[str] = None            # fix the work date (ISO)
    notes: Optional[str] = None           # free-text note


class ResolveValidationRequest(BaseModel):
    resolution_note: Optional[str] = None
    resolved_by_name: Optional[str] = None   # HR reviewer's name for audit trail
    correction: Optional[CorrectionPayload] = None

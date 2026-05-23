"""Pydantic schemas for validation errors."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
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


class ResolveValidationRequest(BaseModel):
    resolution_note: Optional[str] = None

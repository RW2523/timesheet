"""Pydantic schemas for uploaded file operations."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class FileRecord(BaseModel):
    id: str
    batch_id: str
    folder_path: Optional[str]
    file_name: str
    file_ext: Optional[str]
    file_size_bytes: Optional[int]
    file_hash: Optional[str]
    detected_employee_name: Optional[str]
    detected_vendor_name: Optional[str]
    detected_period_text: Optional[str]
    matched_employee_id: Optional[str]
    match_confidence: Optional[float]
    match_status: str
    parser_name: Optional[str]
    ocr_required: bool
    is_duplicate: bool
    is_noise_file: bool
    is_timesheet_candidate: bool
    processing_status: str
    alerts_json: Optional[Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class FileListResponse(BaseModel):
    items: list[FileRecord]
    total: int


class AssignEmployeeRequest(BaseModel):
    employee_id: str
    override_reason: Optional[str] = None


class MarkNonTimesheetRequest(BaseModel):
    reason: Optional[str] = None

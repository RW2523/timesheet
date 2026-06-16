"""Pydantic schemas for batch operations."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class BatchSummary(BaseModel):
    id: str
    source_name: str
    source_type: str
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    ignored_files: int
    duplicate_files: int
    review_required_files: int
    payroll_ready_count: int
    created_at: datetime
    updated_at: datetime
    summary_json: Optional[Any] = None
    filter_period_start: Optional[str] = None
    filter_period_end: Optional[str] = None
    current_file: Optional[str] = None
    current_stage: Optional[str] = None

    model_config = {"from_attributes": True}


class BatchListResponse(BaseModel):
    items: list[BatchSummary]
    total: int


class DashboardStats(BaseModel):
    total_batches: int
    processing_batches: int
    needs_review_batches: int
    payroll_ready_batches: int
    failed_batches: int
    open_blockers: int
    open_warnings: int

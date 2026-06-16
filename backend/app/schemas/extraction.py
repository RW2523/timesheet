"""
Pydantic models for LLM timesheet extraction.

These define the single canonical shape the LLM must produce.  They are used
two ways:
  1. ``timesheet_extraction_schema()`` returns a JSON Schema the model is
     constrained to (Ollama ``format`` / OpenAI ``response_format``).
  2. ``TimesheetExtraction.model_validate(...)`` validates whatever the model
     returned, so a malformed row fails loudly (and triggers a retry) instead
     of silently corrupting payroll.

Kept intentionally permissive on value formats (strings) — deterministic
normalization of dates/times/hours happens downstream in date_utils /
timesheet_service.  The schema's job is structural integrity, not arithmetic.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ExtractedEntry(BaseModel):
    model_config = {"extra": "ignore"}

    date: Optional[str] = Field(default=None, description="Work date, YYYY-MM-DD")
    in_time: Optional[str] = Field(default=None, description="Clock-in, HH:MM 24h")
    out_time: Optional[str] = Field(default=None, description="Clock-out, HH:MM 24h")
    break_minutes: float = Field(default=0.0, description="Unpaid break in minutes")
    hours: Optional[float] = Field(default=None, description="Net worked hours for the day")
    regular_hours: Optional[float] = None
    overtime_hours: Optional[float] = None
    entry_type: str = Field(default="WORK", description="WORK|LEAVE|HOLIDAY|ABSENT|WEEKEND")
    leave_type: Optional[str] = None
    source: str = "FILE_EXTRACTED"
    notes: Optional[str] = None

    @field_validator("break_minutes", mode="before")
    @classmethod
    def _coerce_break(cls, v):
        # LLMs emit "30", "30.0", 30, or "" — coerce to a number, default 0.
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @field_validator("hours", "regular_hours", "overtime_hours", mode="before")
    @classmethod
    def _coerce_hours(cls, v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class TimesheetExtraction(BaseModel):
    model_config = {"extra": "ignore"}

    employee_name: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    approved_by_name: Optional[str] = None
    approved_by_email: Optional[str] = None
    entries: List[ExtractedEntry] = Field(default_factory=list)


def timesheet_extraction_schema() -> dict:
    """JSON Schema for schema-constrained model output."""
    return TimesheetExtraction.model_json_schema()

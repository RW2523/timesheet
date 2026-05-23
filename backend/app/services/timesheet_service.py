"""
Timesheet service — Phase 6.
Creates timesheet_submissions and timesheet_entries from normalized JSON.
Merges partial records, detects duplicate dates.
"""
import logging
from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session

from app.db.models import (
    TimesheetSubmission, TimesheetEntry, ValidationError,
    UploadedFile, RawExtraction, BatchUpload, gen_uuid,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class TimesheetService:
    def __init__(self, db: Session):
        self.db = db

    def create_submissions_for_batch(self, batch_id: str) -> None:
        """Create timesheet submissions and entries for all matched files in a batch."""
        files = (
            self.db.query(UploadedFile)
            .filter(
                UploadedFile.batch_id == batch_id,
                UploadedFile.is_noise_file == False,
                UploadedFile.is_duplicate == False,
                UploadedFile.matched_employee_id.isnot(None),
                UploadedFile.is_timesheet_candidate == True,
            )
            .all()
        )

        batch = self.db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()
        payroll_period_id = batch.payroll_period_id if batch else None

        for file_record in files:
            try:
                self._process_file(file_record, batch_id, payroll_period_id)
            except Exception as e:
                logger.error(f"TimesheetService failed for file {file_record.id}: {e}", exc_info=True)

        self.db.commit()

    def _process_file(
        self,
        file_record: UploadedFile,
        batch_id: str,
        payroll_period_id: Optional[str],
    ) -> None:
        raw = (
            self.db.query(RawExtraction)
            .filter(RawExtraction.file_id == file_record.id)
            .first()
        )
        if not raw or not raw.llm_json:
            return

        extracted = raw.llm_json
        entries_data = extracted.get("entries", [])
        if not entries_data:
            return

        period_start = self._parse_date(extracted.get("period_start"))
        period_end = self._parse_date(extracted.get("period_end"))
        if not period_start and entries_data:
            period_start = self._parse_date(entries_data[0].get("date"))
        if not period_end and entries_data:
            period_end = self._parse_date(entries_data[-1].get("date"))

        # Find or create submission for this employee+period
        submission = self._find_or_create_submission(
            employee_id=file_record.matched_employee_id,
            file_id=file_record.id,
            batch_id=batch_id,
            payroll_period_id=payroll_period_id,
            period_start=period_start,
            period_end=period_end,
            extracted=extracted,
        )

        # Create entries
        for entry_data in entries_data:
            work_date = self._parse_date(entry_data.get("date"))
            if not work_date:
                continue

            # Check for duplicate date for this submission
            existing = (
                self.db.query(TimesheetEntry)
                .filter(
                    TimesheetEntry.submission_id == submission.id,
                    TimesheetEntry.work_date == work_date,
                )
                .first()
            )
            if existing:
                # Flag as duplicate date — will be caught by validation
                self._add_validation_error(
                    batch_id=batch_id,
                    file_id=file_record.id,
                    submission_id=submission.id,
                    employee_id=file_record.matched_employee_id,
                    rule_code="DUPLICATE_DATE",
                    severity="ERROR",
                    message=f"Duplicate entry for date {work_date}",
                    actual_value=str(work_date),
                )
                continue

            in_time = self._parse_time(entry_data.get("in_time"))
            out_time = self._parse_time(entry_data.get("out_time"))
            break_min = int(entry_data.get("break_minutes") or 0)
            entered_hours = entry_data.get("hours")
            if entered_hours is not None:
                try:
                    entered_hours = float(entered_hours)
                except (ValueError, TypeError):
                    entered_hours = None

            # Calculate hours deterministically
            calculated_hours = self._calculate_hours(in_time, out_time, break_min, entered_hours)

            # Split regular / overtime
            regular_h, ot_h = self._split_regular_overtime(calculated_hours)

            entry = TimesheetEntry(
                id=gen_uuid(),
                submission_id=submission.id,
                employee_id=file_record.matched_employee_id,
                work_date=work_date,
                day_of_week=work_date.strftime("%A") if work_date else None,
                in_time=in_time,
                out_time=out_time,
                break_minutes=break_min,
                entered_hours=entered_hours,
                calculated_hours=calculated_hours,
                regular_hours=regular_h,
                overtime_hours=ot_h,
                entry_type=entry_data.get("entry_type", "WORK"),
                leave_type=entry_data.get("leave_type"),
                source_file_id=file_record.id,
                row_source=entry_data,
                validation_status="PENDING",
            )
            self.db.add(entry)

        file_record.processing_status = "COMPLETED"
        file_record.updated_at = datetime.utcnow()
        self.db.commit()

    def _find_or_create_submission(
        self,
        employee_id: str,
        file_id: str,
        batch_id: str,
        payroll_period_id: Optional[str],
        period_start: Optional[date],
        period_end: Optional[date],
        extracted: dict,
    ) -> TimesheetSubmission:
        """Find existing submission for same employee+period or create new one."""
        if payroll_period_id:
            existing = (
                self.db.query(TimesheetSubmission)
                .filter(
                    TimesheetSubmission.batch_id == batch_id,
                    TimesheetSubmission.employee_id == employee_id,
                    TimesheetSubmission.payroll_period_id == payroll_period_id,
                )
                .first()
            )
            if existing:
                return existing

        sub = TimesheetSubmission(
            id=gen_uuid(),
            batch_id=batch_id,
            file_id=file_id,
            employee_id=employee_id,
            payroll_period_id=payroll_period_id,
            source_type="ZIP_UPLOAD",
            submission_date=datetime.utcnow(),
            timesheet_start_date=period_start,
            timesheet_end_date=period_end,
            approved_by_name=extracted.get("approved_by_name"),
            approved_by_email=extracted.get("approved_by_email"),
            approval_status="PENDING",
            validation_status="PENDING",
            payroll_status="NOT_READY",
        )
        self.db.add(sub)
        self.db.flush()
        return sub

    @staticmethod
    def _calculate_hours(
        in_time: Optional[time],
        out_time: Optional[time],
        break_min: int,
        entered_hours: Optional[float],
    ) -> Optional[float]:
        """Deterministic hour calculation. Never delegated to LLM."""
        if in_time and out_time:
            in_mins = in_time.hour * 60 + in_time.minute
            out_mins = out_time.hour * 60 + out_time.minute
            if out_mins < in_mins:  # crosses midnight
                out_mins += 24 * 60
            total_mins = out_mins - in_mins - break_min
            return round(max(total_mins, 0) / 60.0, 2)
        return entered_hours

    @staticmethod
    def _split_regular_overtime(hours: Optional[float]) -> tuple[float, float]:
        """Split hours into regular and overtime."""
        if hours is None:
            return 0.0, 0.0
        daily_limit = settings.REGULAR_DAILY_LIMIT_HOURS
        if hours <= daily_limit:
            return hours, 0.0
        return daily_limit, round(hours - daily_limit, 2)

    @staticmethod
    def _parse_date(val) -> Optional[date]:
        if not val:
            return None
        try:
            if isinstance(val, date):
                return val
            from dateutil import parser as dp
            return dp.parse(str(val)).date()
        except Exception:
            return None

    @staticmethod
    def _parse_time(val) -> Optional[time]:
        if not val:
            return None
        try:
            if isinstance(val, time):
                return val
            from dateutil import parser as dp
            return dp.parse(str(val)).time()
        except Exception:
            return None

    def _add_validation_error(self, **kwargs) -> None:
        err = ValidationError(id=gen_uuid(), **kwargs, status="OPEN")
        self.db.add(err)

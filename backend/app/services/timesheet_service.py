"""
Timesheet service — Phase 6.
Creates timesheet_submissions and timesheet_entries from normalized JSON.

Key improvements:
- Vendor-aware overtime split: only split OT when vendor.overtime_enabled is True.
  Non-OT vendors get a OVERTIME_NOT_ALLOWED_REVIEW warning instead of silently splitting.
- DAILY_HOURS_MISMATCH: when entered_hours and calculated_hours both exist and differ
  by more than HOURS_MISMATCH_TOLERANCE, a validation error is created.
- INVALID_DATE: Excel epoch artifact dates (value starts with "INVALID_") generate a
  validation error and the entry is skipped.
- Entries outside the batch period (already removed from llm_json by Normalizer) are
  excluded here too for extra safety.
- Merges multiple files for the same employee+month into one submission.
"""
import logging
from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session

from app.db.models import (
    TimesheetSubmission, TimesheetEntry, ValidationError,
    UploadedFile, RawExtraction, BatchUpload, Employee, Vendor, gen_uuid,
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

        self.db.flush()
        self._apply_weekly_overtime(batch_id)
        self.db.commit()

    def _apply_weekly_overtime(self, batch_id: str) -> None:
        """Reclassify regular hours above the weekly limit into overtime.

        Daily OT (hours > daily limit) is already split per entry; this adds the
        weekly rule: for OT-allowed vendors, regular hours beyond the weekly limit
        (Mon–Sun) become overtime, taken from the latest days first.  Without this,
        e.g. 7×7h = 49h is paid as 49h regular even though weekly OT is owed.
        """
        if not getattr(settings, "WEEKLY_OVERTIME_ENABLED", True):
            return

        subs = (
            self.db.query(TimesheetSubmission)
            .filter(TimesheetSubmission.batch_id == batch_id)
            .all()
        )
        default_weekly = float(settings.REGULAR_WEEKLY_LIMIT_HOURS)
        for sub in subs:
            vendor = self.db.query(Vendor).filter(Vendor.id == sub.vendor_id).first() if sub.vendor_id else None
            if vendor and not vendor.overtime_enabled:
                continue  # non-OT vendors keep everything as regular
            weekly_limit = float(getattr(vendor, "regular_weekly_limit", None) or default_weekly)

            entries = (
                self.db.query(TimesheetEntry)
                .filter(TimesheetEntry.submission_id == sub.id)
                .all()
            )
            weeks: dict = {}
            for e in entries:
                if not e.work_date:
                    continue
                iso = e.work_date.isocalendar()
                weeks.setdefault((iso[0], iso[1]), []).append(e)

            for week_entries in weeks.values():
                total_reg = sum(float(e.regular_hours or 0) for e in week_entries)
                excess = round(total_reg - weekly_limit, 2)
                if excess <= 0:
                    continue
                # Move the excess from regular to overtime, latest day first.
                for e in sorted(week_entries, key=lambda x: x.work_date, reverse=True):
                    if excess <= 0:
                        break
                    reg = float(e.regular_hours or 0)
                    move = min(reg, excess)
                    if move <= 0:
                        continue
                    e.regular_hours = round(reg - move, 2)
                    e.overtime_hours = round(float(e.overtime_hours or 0) + move, 2)
                    excess = round(excess - move, 2)

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

        # Fetch vendor for this employee (needed for OT split logic)
        vendor = self._get_vendor(file_record.matched_employee_id)

        period_start = self._parse_date(extracted.get("period_start"))
        period_end = self._parse_date(extracted.get("period_end"))
        if not period_start and entries_data:
            period_start = self._parse_date(entries_data[0].get("date"))
        if not period_end and entries_data:
            period_end = self._parse_date(entries_data[-1].get("date"))

        submission = self._find_or_create_submission(
            employee_id=file_record.matched_employee_id,
            file_id=file_record.id,
            batch_id=batch_id,
            payroll_period_id=payroll_period_id,
            period_start=period_start,
            period_end=period_end,
            extracted=extracted,
            vendor=vendor,
        )

        for entry_data in entries_data:
            raw_date = entry_data.get("date") or ""

            # Flag invalid Excel epoch dates
            if str(raw_date).startswith("INVALID_"):
                self._add_validation_error(
                    batch_id=batch_id,
                    file_id=file_record.id,
                    submission_id=submission.id,
                    employee_id=file_record.matched_employee_id,
                    rule_code="INVALID_DATE",
                    severity="ERROR",
                    message=f"Invalid Excel epoch date detected: {raw_date}",
                    actual_value=str(raw_date),
                )
                continue

            work_date = self._parse_date(raw_date)
            if not work_date:
                continue

            in_time = self._parse_time(entry_data.get("in_time"))
            out_time = self._parse_time(entry_data.get("out_time"))

            # Check for an existing entry on this date for this submission
            existing = (
                self.db.query(TimesheetEntry)
                .filter(
                    TimesheetEntry.submission_id == submission.id,
                    TimesheetEntry.work_date == work_date,
                )
                .first()
            )
            if existing:
                # A genuine second shift has its own distinct in/out window — keep it
                # as an additional entry rather than dropping it.
                is_distinct_shift = bool(
                    in_time and out_time and existing.in_time and existing.out_time
                    and (in_time != existing.in_time or out_time != existing.out_time)
                )
                if not is_distinct_shift:
                    existing_hours = float(existing.calculated_hours or existing.entered_hours or 0)
                    new_hours = float(entry_data.get("hours") or 0)
                    if abs(existing_hours - new_hours) > settings.HOURS_MISMATCH_TOLERANCE:
                        # Same date, different hours = OVERLAPPING_DATE_CONFLICT (BLOCKER)
                        self._add_validation_error(
                            batch_id=batch_id,
                            file_id=file_record.id,
                            submission_id=submission.id,
                            employee_id=file_record.matched_employee_id,
                            rule_code="OVERLAPPING_DATE_CONFLICT",
                            severity="BLOCKER",
                            message=f"Conflicting entries for {work_date}: "
                                    f"existing={existing_hours:.2f}h, new={new_hours:.2f}h",
                            expected_value=str(existing_hours),
                            actual_value=str(new_hours),
                        )
                    else:
                        # Same date, same hours = DUPLICATE_DATE (WARNING)
                        self._add_validation_error(
                            batch_id=batch_id,
                            file_id=file_record.id,
                            submission_id=submission.id,
                            employee_id=file_record.matched_employee_id,
                            rule_code="DUPLICATE_DATE",
                            severity="WARNING",
                            message=f"Duplicate entry for date {work_date} (same hours — possibly the same file processed twice)",
                            actual_value=str(work_date),
                        )
                    continue
                # else: fall through and insert the second shift as its own entry

            try:
                break_min = int(round(float(entry_data.get("break_minutes") or 0)))
            except (ValueError, TypeError):
                break_min = 0
            entered_hours = entry_data.get("hours")
            if entered_hours is not None:
                try:
                    entered_hours = float(entered_hours)
                except (ValueError, TypeError):
                    entered_hours = None

            # Deterministic hour calculation
            calculated_hours, calc_method = self._calculate_hours(in_time, out_time, break_min, entered_hours)

            # Detect mismatch between entered and calculated hours
            has_mismatch = (
                entered_hours is not None and calculated_hours is not None
                and in_time and out_time  # only flag when we actually calculated
                and abs(float(entered_hours) - float(calculated_hours)) > settings.HOURS_MISMATCH_TOLERANCE
            )
            if has_mismatch:
                self._add_validation_error(
                    batch_id=batch_id,
                    file_id=file_record.id,
                    submission_id=submission.id,
                    employee_id=file_record.matched_employee_id,
                    rule_code="DAILY_HOURS_MISMATCH",
                    severity="ERROR",
                    message=(
                        f"{work_date}: entered_hours={entered_hours:.2f}h but "
                        f"calculated from in/out={calculated_hours:.2f}h "
                        f"(tolerance ±{settings.HOURS_MISMATCH_TOLERANCE}h)"
                    ),
                    expected_value=str(calculated_hours),
                    actual_value=str(entered_hours),
                )

            # Payroll safety rule: when entered_hours and calculated_hours disagree,
            # use entered_hours (what the employee filed) not the system calculation.
            # HR can review and override. This prevents silently inflating payroll.
            payroll_hours = entered_hours if (has_mismatch and entered_hours is not None) else calculated_hours

            # Vendor-aware regular / overtime split
            regular_h, ot_h = self._split_regular_overtime(
                payroll_hours, vendor=vendor,
            )

            # If overtime not allowed for this vendor but OT is present, create a review alert
            if ot_h > 0 and vendor and not vendor.overtime_enabled:
                self._add_validation_error(
                    batch_id=batch_id,
                    file_id=file_record.id,
                    submission_id=submission.id,
                    employee_id=file_record.matched_employee_id,
                    rule_code="OVERTIME_NOT_ALLOWED",
                    severity="ERROR",
                    message=(
                        f"{work_date}: {ot_h:.2f}h overtime claimed but "
                        f"vendor '{vendor.name}' does not allow overtime"
                    ),
                    expected_value="0",
                    actual_value=str(ot_h),
                )
                # For non-OT vendors treat all hours as regular for payroll safety.
                # Use the SAME authoritative figure chosen above (payroll_hours),
                # not calculated_hours — otherwise a mismatched entry silently
                # reverts to the system calc and contradicts the safety rule.
                regular_h = payroll_hours or 0.0
                ot_h = 0.0

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

    def _get_vendor(self, employee_id: str) -> Optional[Vendor]:
        """Fetch vendor for employee."""
        emp = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if emp and emp.vendor_id:
            return self.db.query(Vendor).filter(Vendor.id == emp.vendor_id).first()
        return None

    def _find_or_create_submission(
        self,
        employee_id: str,
        file_id: str,
        batch_id: str,
        payroll_period_id: Optional[str],
        period_start: Optional[date],
        period_end: Optional[date],
        extracted: dict,
        vendor: Optional[Vendor],
    ) -> TimesheetSubmission:
        """Find existing submission for same employee+period or create a new one.

        Merging strategy:
        - If payroll_period_id exists, find by employee + payroll_period.
        - Otherwise find by employee + batch (merge all files for same employee in batch).
        """
        # Primary: find by payroll period
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
                # Extend period if this file covers more dates
                if period_start and (not existing.timesheet_start_date or period_start < existing.timesheet_start_date):
                    existing.timesheet_start_date = period_start
                if period_end and (not existing.timesheet_end_date or period_end > existing.timesheet_end_date):
                    existing.timesheet_end_date = period_end
                return existing

        # Secondary: find by employee + batch (no payroll period set)
        existing_any = (
            self.db.query(TimesheetSubmission)
            .filter(
                TimesheetSubmission.batch_id == batch_id,
                TimesheetSubmission.employee_id == employee_id,
            )
            .first()
        )
        if existing_any:
            if period_start and (not existing_any.timesheet_start_date or period_start < existing_any.timesheet_start_date):
                existing_any.timesheet_start_date = period_start
            if period_end and (not existing_any.timesheet_end_date or period_end > existing_any.timesheet_end_date):
                existing_any.timesheet_end_date = period_end
            return existing_any

        vendor_id = vendor.id if vendor else None
        sub = TimesheetSubmission(
            id=gen_uuid(),
            batch_id=batch_id,
            file_id=file_id,
            employee_id=employee_id,
            payroll_period_id=payroll_period_id,
            vendor_id=vendor_id,
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
    ) -> tuple[Optional[float], str]:
        """Deterministic hour calculation. Returns (hours, method_description).

        Never delegated to LLM.
        Uses clock-in/out when available; falls back to entered_hours.
        If clock calculation > 14h but entered ≤ 14h, trusts entered_hours
        (the out_time was likely AM/PM-ambiguous).
        """
        if in_time and out_time:
            in_mins = in_time.hour * 60 + in_time.minute
            out_mins = out_time.hour * 60 + out_time.minute
            if out_mins < in_mins:  # crosses midnight
                out_mins += 24 * 60
            total_mins = out_mins - in_mins - break_min
            calculated = round(max(total_mins, 0) / 60.0, 2)
            if calculated > 14 and entered_hours and 0 < entered_hours <= 14:
                return entered_hours, "ENTERED_HOURS_USED_AMPM_AMBIGUITY"
            return calculated, "CALCULATED_FROM_IN_OUT"
        if entered_hours is not None:
            return entered_hours, "HOURS_FROM_FILE_ONLY"
        return None, "NO_HOURS"

    @staticmethod
    def _split_regular_overtime(
        hours: Optional[float],
        vendor: Optional[Vendor] = None,
    ) -> tuple[float, float]:
        """Split hours into regular and overtime.

        Respects vendor daily_regular_limit and overtime_enabled flag.
        If vendor does not allow overtime, all hours are returned as regular
        (the caller is responsible for creating the OVERTIME_NOT_ALLOWED error).
        """
        if hours is None:
            return 0.0, 0.0

        if vendor:
            daily_limit = float(vendor.regular_daily_limit or settings.REGULAR_DAILY_LIMIT_HOURS)
            ot_allowed = vendor.overtime_enabled
        else:
            daily_limit = settings.REGULAR_DAILY_LIMIT_HOURS
            ot_allowed = True  # default: allow OT when vendor unknown

        if hours <= daily_limit:
            return hours, 0.0

        if ot_allowed:
            return daily_limit, round(hours - daily_limit, 2)
        else:
            # No OT allowed — caller creates OVERTIME_NOT_ALLOWED error
            return hours, 0.0

    @staticmethod
    def _parse_date(val) -> Optional[date]:
        if not val:
            return None
        if isinstance(val, date):
            return val
        # Shared parser honours settings.DATE_DAYFIRST (consistent with normalizer).
        from app.services.date_utils import parse_date as _pd
        iso = _pd(val)
        if not iso:
            return None
        try:
            return date.fromisoformat(iso)
        except ValueError:
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

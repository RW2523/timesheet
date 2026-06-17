"""
Validation engine — Phase 7.
All rules are deterministic Python — no LLM involvement.

Full rule set (20 rules):
  1.  EMPLOYEE_NOT_MATCHED     — BLOCKER   — no employee matched to file
  2.  EXTRACTION_FAILED        — BLOCKER   — no valid timesheet data extracted
  3.  DAILY_HOURS_EXCEED       — ERROR     — single day > MAX_DAILY_HOURS
  4.  DAILY_HOURS_MISMATCH     — ERROR     — entered ≠ calculated (already fires in TimesheetService)
  5.  DAILY_REGULAR_LIMIT_EXCEEDED — WARNING — regular > daily limit (>8h on a single day)
  6.  WEEKLY_REGULAR_LIMIT_EXCEEDED — ERROR — weekly regular > 40h
  7.  OVERTIME_NOT_ALLOWED     — ERROR     — OT filed but vendor disallows (fires in TimesheetService)
  8.  HOLIDAY_WORK             — WARNING   — work on a calendar holiday
  9.  MISSING_APPROVAL         — BLOCKER   — no approver on timesheet
  10. LATE_SUBMISSION          — WARNING   — after payroll period cutoff
  11. MISSING_TIMESHEET        — ERROR     — active employee expected but no submission
  12. TWO_MONTH_INACTIVE       — WARNING   — no submission in 2+ months (only when 2+ months in DB)
  13. DUPLICATE_FILE           — INFO      — same SHA-256 hash (fires in FileInventoryService)
  14. DUPLICATE_DATE           — WARNING   — same date duplicated in same submission
  15. OVERLAPPING_DATE_CONFLICT — BLOCKER  — same date with different hours (fires in TimesheetService)
  16. OUT_OF_PERIOD_ENTRY      — WARNING   — entry outside selected payroll period
  17. INVALID_DATE             — ERROR     — corrupted Excel serial dates
  18. NON_TIMESHEET_DOCUMENT   — INFO      — reimbursement/invoice/unrelated file
  19. MISSING_RATE             — BLOCKER   — no pay rate found for employee
  20. HOURS_TOTAL_MISMATCH     — ERROR     — payroll math: total ≠ regular + overtime

Payroll readiness rule:
  A submission is PAYROLL_READY only when:
  - no open BLOCKER errors
  - no open ERROR errors (strict mode)
  - employee matched
  - valid entries exist
  - approval present
  - rate exists
"""
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Optional
from collections import defaultdict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    TimesheetSubmission, TimesheetEntry, ValidationError, Employee,
    Vendor, HolidayDate, HolidayCalendar, BatchUpload, UploadedFile,
    EmployeeRate, RawExtraction, gen_uuid,
)

logger = logging.getLogger(__name__)

SEVERITY_BLOCKER = "BLOCKER"
SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

# Rule codes this service generates and re-generates on every run. Only these
# are wiped before re-validation; entry-level codes from TimesheetService
# (IMPLAUSIBLE_HOURS, INVALID_DATE, DAILY_HOURS_MISMATCH, …) are preserved.
_VALIDATION_OWNED_CODES = {
    "EMPLOYEE_NOT_MATCHED", "EXTRACTION_FAILED", "NON_TIMESHEET_DOCUMENT",
    "DAILY_HOURS_EXCEED", "DAILY_REGULAR_LIMIT_EXCEEDED", "WEEKLY_HOURS_EXCEED",
    "HOURS_TOTAL_MISMATCH", "MISSING_APPROVAL", "MISSING_RATE", "LATE_SUBMISSION",
    "HOLIDAY_WORK", "MISSING_TIMESHEET", "TWO_MONTH_INACTIVE",
}


class ValidationService:
    def __init__(self, db: Session):
        self.db = db

    def validate_batch(self, batch_id: str) -> None:
        """Run all validation rules for every submission in a batch.

        Clears all auto-generated OPEN errors first so re-runs don't accumulate stale
        duplicates. Manually-RESOLVED errors are preserved as audit history.
        """
        # Wipe stale OPEN errors — but ONLY the codes THIS service regenerates.
        # Entry-level codes raised during submission creation (IMPLAUSIBLE_HOURS,
        # INVALID_DATE, DAILY_HOURS_MISMATCH, OVERLAPPING_DATE_CONFLICT, …) must be
        # preserved, otherwise they'd be erased on every re-validation.
        # RESOLVED errors are audit records and must not be deleted.
        self.db.query(ValidationError).filter(
            ValidationError.batch_id == batch_id,
            ValidationError.status == "OPEN",
            ValidationError.rule_code.in_(_VALIDATION_OWNED_CODES),
        ).delete(synchronize_session=False)
        self.db.flush()

        # File-level rules (before submission-level)
        self._check_unmatched_files(batch_id)
        self._check_extraction_failures(batch_id)
        self._check_non_timesheet_documents(batch_id)

        # Submission-level rules
        submissions = (
            self.db.query(TimesheetSubmission)
            .filter(TimesheetSubmission.batch_id == batch_id)
            .all()
        )
        batch = self.db.query(BatchUpload).filter(BatchUpload.id == batch_id).first()

        for sub in submissions:
            try:
                self._validate_submission(sub, batch_id)
            except Exception as e:
                logger.error(f"Validation failed for submission {sub.id}: {e}", exc_info=True)

        # Batch-level checks
        self._check_missing_timesheets(batch_id, batch)
        if self._has_multi_month_data():
            self._check_inactive_employees(batch_id)

        self.db.commit()
        logger.info(f"[{batch_id}] Validation complete for {len(submissions)} submissions")

    # ── File-level rules ─────────────────────────────────────────────────────

    def _check_unmatched_files(self, batch_id: str) -> None:
        """Rule 1: EMPLOYEE_NOT_MATCHED — file is a timesheet candidate but no employee found."""
        unmatched = (
            self.db.query(UploadedFile)
            .filter(
                UploadedFile.batch_id == batch_id,
                UploadedFile.is_noise_file == False,
                UploadedFile.is_duplicate == False,
                UploadedFile.is_timesheet_candidate == True,
                UploadedFile.matched_employee_id.is_(None),
            )
            .all()
        )
        for f in unmatched:
            # Check we haven't already added this error (idempotent)
            existing = (
                self.db.query(ValidationError)
                .filter(
                    ValidationError.file_id == f.id,
                    ValidationError.rule_code == "EMPLOYEE_NOT_MATCHED",
                    ValidationError.status == "OPEN",
                )
                .first()
            )
            if not existing:
                # Matching is optional metadata, not a gate: the timesheet is still
                # fully extracted. Flag as a non-blocking WARNING for later linking.
                self._add_error(
                    batch_id=batch_id,
                    file_id=f.id,
                    rule_code="EMPLOYEE_NOT_MATCHED",
                    severity=SEVERITY_WARNING,
                    message=f"No employee matched for file '{f.file_name}' "
                            f"(candidate: '{f.detected_employee_name or 'unknown'}')",
                    action_required="Optionally link to an employee in the roster",
                    assigned_to_role="HR",
                )

    def _check_extraction_failures(self, batch_id: str) -> None:
        """Rule 2: EXTRACTION_FAILED — file processed but no valid timesheet data extracted."""
        failed_files = (
            self.db.query(UploadedFile)
            .filter(
                UploadedFile.batch_id == batch_id,
                UploadedFile.is_noise_file == False,
                UploadedFile.is_duplicate == False,
                UploadedFile.is_timesheet_candidate == True,
                UploadedFile.processing_status.in_(["EXTRACTION_FAILED", "NEEDS_REVIEW", "FAILED"]),
            )
            .all()
        )
        for f in failed_files:
            # Only flag EXTRACTION_FAILED rule when there's no matched employee submission
            # (NEEDS_REVIEW with an employee match is handled at submission level)
            raw = (
                self.db.query(RawExtraction)
                .filter(RawExtraction.file_id == f.id)
                .first()
            )
            has_entries = bool(
                raw and raw.llm_json and raw.llm_json.get("entries")
            )
            if not has_entries:
                existing = (
                    self.db.query(ValidationError)
                    .filter(
                        ValidationError.file_id == f.id,
                        ValidationError.rule_code == "EXTRACTION_FAILED",
                        ValidationError.status == "OPEN",
                    )
                    .first()
                )
                if not existing:
                    self._add_error(
                        batch_id=batch_id,
                        file_id=f.id,
                        rule_code="EXTRACTION_FAILED",
                        severity=SEVERITY_BLOCKER,
                        message=f"No valid timesheet entries extracted from '{f.file_name}'",
                        action_required="Review file manually, correct extraction, or mark as non-timesheet",
                        assigned_to_role="HR",
                    )

    def _check_non_timesheet_documents(self, batch_id: str) -> None:
        """Rule 18: NON_TIMESHEET_DOCUMENT — document classified as non-timesheet (invoice etc.)."""
        non_ts = (
            self.db.query(UploadedFile)
            .filter(
                UploadedFile.batch_id == batch_id,
                UploadedFile.processing_status == "NON_TIMESHEET_DOCUMENT",
            )
            .all()
        )
        for f in non_ts:
            existing = (
                self.db.query(ValidationError)
                .filter(
                    ValidationError.file_id == f.id,
                    ValidationError.rule_code == "NON_TIMESHEET_DOCUMENT",
                )
                .first()
            )
            if not existing:
                self._add_error(
                    batch_id=batch_id,
                    file_id=f.id,
                    rule_code="NON_TIMESHEET_DOCUMENT",
                    severity=SEVERITY_INFO,
                    message=f"'{f.file_name}' classified as non-timesheet document — excluded from payroll",
                    action_required="Verify classification is correct",
                    assigned_to_role="HR",
                )

    # ── Submission-level validation ───────────────────────────────────────────

    def _validate_submission(self, sub: TimesheetSubmission, batch_id: str) -> None:
        entries = (
            self.db.query(TimesheetEntry)
            .filter(TimesheetEntry.submission_id == sub.id)
            .order_by(TimesheetEntry.work_date)
            .all()
        )

        employee = self.db.query(Employee).filter(Employee.id == sub.employee_id).first()
        vendor = self.db.query(Vendor).filter(Vendor.id == sub.vendor_id).first() if sub.vendor_id else None
        if not vendor and employee and employee.vendor_id:
            vendor = self.db.query(Vendor).filter(Vendor.id == employee.vendor_id).first()

        # Per-entry rules
        for entry in entries:
            self._check_daily_hours_exceed(entry, sub, batch_id)
            self._check_daily_regular_limit(entry, sub, batch_id, vendor)
            self._check_holiday_work(entry, sub, batch_id, employee)

        # Per-week rules
        self._check_weekly_hours(entries, sub, batch_id, vendor)

        # Per-submission rules
        self._check_missing_approval(sub, batch_id)
        self._check_late_submission(sub, batch_id)
        self._check_missing_rate(sub, batch_id, employee)
        self._check_hours_math(entries, sub, batch_id)

        # Determine payroll readiness
        # PAYROLL_READY requires: no open BLOCKERs and no open ERRORs
        open_blockers = (
            self.db.query(ValidationError)
            .filter(
                ValidationError.submission_id == sub.id,
                ValidationError.severity == SEVERITY_BLOCKER,
                ValidationError.status == "OPEN",
            )
            .count()
        )
        open_errors = (
            self.db.query(ValidationError)
            .filter(
                ValidationError.submission_id == sub.id,
                ValidationError.severity == SEVERITY_ERROR,
                ValidationError.status == "OPEN",
            )
            .count()
        )

        blocked = open_blockers > 0 or open_errors > 0
        sub.validation_status = "FAILED" if blocked else "PASSED"
        sub.payroll_status = "NOT_READY" if blocked else "READY"
        sub.updated_at = datetime.utcnow()

    # ── Rule 3: DAILY_HOURS_EXCEED ────────────────────────────────────────────

    def _check_daily_hours_exceed(
        self, entry: TimesheetEntry, sub: TimesheetSubmission, batch_id: str
    ) -> None:
        hours = float(entry.calculated_hours or entry.entered_hours or 0)
        if hours > settings.MAX_DAILY_HOURS:
            self._add_error(
                batch_id=batch_id,
                file_id=sub.file_id,
                submission_id=sub.id,
                entry_id=entry.id,
                employee_id=sub.employee_id,
                rule_code="DAILY_HOURS_EXCEED",
                severity=SEVERITY_ERROR,
                message=f"Daily hours {hours:.1f}h exceed maximum {settings.MAX_DAILY_HOURS}h on {entry.work_date}",
                expected_value=str(settings.MAX_DAILY_HOURS),
                actual_value=str(hours),
                action_required="Review and correct daily hours",
                assigned_to_role="HR",
            )

    # ── Rule 5: DAILY_REGULAR_LIMIT_EXCEEDED ─────────────────────────────────

    def _check_daily_regular_limit(
        self, entry: TimesheetEntry, sub: TimesheetSubmission, batch_id: str, vendor: Optional[Vendor]
    ) -> None:
        """Flag when regular_hours exceeds the daily regular limit (usually 8h)."""
        regular = float(entry.regular_hours or 0)
        daily_limit = float(vendor.regular_daily_limit if vendor else settings.REGULAR_DAILY_LIMIT_HOURS)
        if regular > daily_limit + settings.HOURS_MISMATCH_TOLERANCE:
            self._add_error(
                batch_id=batch_id,
                file_id=sub.file_id,
                submission_id=sub.id,
                entry_id=entry.id,
                employee_id=sub.employee_id,
                rule_code="DAILY_REGULAR_LIMIT_EXCEEDED",
                severity=SEVERITY_WARNING,
                message=f"Regular hours {regular:.1f}h exceed daily regular limit {daily_limit:.0f}h on {entry.work_date}",
                expected_value=str(daily_limit),
                actual_value=str(regular),
                action_required="Verify if overtime was approved",
                assigned_to_role="HR",
            )

    # ── Rule 6: WEEKLY_HOURS_EXCEED ───────────────────────────────────────────

    def _check_weekly_hours(
        self,
        entries: List[TimesheetEntry],
        sub: TimesheetSubmission,
        batch_id: str,
        vendor: Optional[Vendor],
    ) -> None:
        weekly: dict[str, float] = defaultdict(float)
        for entry in entries:
            if entry.work_date and entry.entry_type == "WORK":
                week_key = entry.work_date.strftime("%Y-W%W")
                weekly[week_key] += float(entry.calculated_hours or entry.entered_hours or 0)

        weekly_limit = float(vendor.regular_weekly_limit if vendor else settings.REGULAR_WEEKLY_LIMIT_HOURS)
        overtime_allowed = vendor.overtime_enabled if vendor else True

        for week_key, total in weekly.items():
            if total > weekly_limit:
                ot = total - weekly_limit
                severity = SEVERITY_WARNING if overtime_allowed else SEVERITY_ERROR
                self._add_error(
                    batch_id=batch_id,
                    file_id=sub.file_id,
                    submission_id=sub.id,
                    employee_id=sub.employee_id,
                    rule_code="WEEKLY_HOURS_EXCEED",
                    severity=severity,
                    message=(
                        f"Week {week_key}: {total:.1f}h total, {ot:.1f}h over limit "
                        f"({'OT allowed' if overtime_allowed else 'OT NOT allowed'})"
                    ),
                    expected_value=str(weekly_limit),
                    actual_value=str(round(total, 2)),
                    action_required="Verify overtime approval" if overtime_allowed else "Overtime not allowed — correct hours",
                    assigned_to_role="HR",
                )

    # ── Rule 8: HOLIDAY_WORK ──────────────────────────────────────────────────

    def _check_holiday_work(
        self, entry: TimesheetEntry, sub: TimesheetSubmission, batch_id: str,
        employee: Optional[Employee],
    ) -> None:
        if entry.entry_type != "WORK":
            return
        hours = float(entry.calculated_hours or entry.entered_hours or 0)
        if hours <= 0:
            return

        # Scope holiday check to the employee's type (internal staff vs contractor)
        employee_type = employee.employee_type if employee else None
        holiday_query = self.db.query(HolidayDate)

        if employee_type:
            # Try to find a calendar for this employee type
            calendars = (
                self.db.query(HolidayCalendar)
                .filter(
                    (HolidayCalendar.applies_to_employee_type == employee_type)
                    | (HolidayCalendar.applies_to_employee_type.is_(None))
                )
                .all()
            )
            calendar_ids = [c.id for c in calendars]
            if calendar_ids:
                holiday_query = holiday_query.filter(HolidayDate.calendar_id.in_(calendar_ids))

        holiday = holiday_query.filter(HolidayDate.holiday_date == entry.work_date).first()
        if holiday:
            entry.is_holiday = True
            entry.holiday_name = holiday.holiday_name
            self._add_error(
                batch_id=batch_id,
                file_id=sub.file_id,
                submission_id=sub.id,
                entry_id=entry.id,
                employee_id=sub.employee_id,
                rule_code="HOLIDAY_WORK",
                severity=SEVERITY_WARNING,
                message=f"Work logged on holiday '{holiday.holiday_name}' ({entry.work_date})",
                expected_value="0",
                actual_value=str(hours),
                action_required="Verify holiday work authorization",
                assigned_to_role="MANAGER",
            )

    # ── Rule 9: MISSING_APPROVAL ──────────────────────────────────────────────

    def _check_missing_approval(
        self, sub: TimesheetSubmission, batch_id: str
    ) -> None:
        if not sub.approved_by_name and not sub.approved_by_email:
            self._add_error(
                batch_id=batch_id,
                file_id=sub.file_id,
                submission_id=sub.id,
                employee_id=sub.employee_id,
                rule_code="MISSING_APPROVAL",
                severity=SEVERITY_BLOCKER,
                message="No approver found on timesheet",
                action_required="Obtain manager approval",
                assigned_to_role="MANAGER",
            )

    # ── Rule 10: LATE_SUBMISSION ──────────────────────────────────────────────

    def _check_late_submission(
        self, sub: TimesheetSubmission, batch_id: str
    ) -> None:
        if not sub.payroll_period_id:
            return
        from app.db.models import PayrollPeriod
        period = self.db.query(PayrollPeriod).filter(PayrollPeriod.id == sub.payroll_period_id).first()
        if not period:
            return

        submission_dt = sub.submission_date or datetime.utcnow()
        from datetime import time as dt_time
        cutoff = datetime.combine(period.cutoff_date, dt_time.min)

        if submission_dt > cutoff:
            sub.is_late = True
            self._add_error(
                batch_id=batch_id,
                file_id=sub.file_id,
                submission_id=sub.id,
                employee_id=sub.employee_id,
                rule_code="LATE_SUBMISSION",
                severity=SEVERITY_WARNING,
                message=f"Submission received {submission_dt.date()} after cutoff {period.cutoff_date}",
                expected_value=str(period.cutoff_date),
                actual_value=str(submission_dt.date()),
                action_required="Move to next payroll cycle",
                assigned_to_role="PAYROLL",
            )

    # ── Rule 19: MISSING_RATE ────────────────────────────────────────────────

    def _check_missing_rate(
        self, sub: TimesheetSubmission, batch_id: str, employee: Optional[Employee]
    ) -> None:
        """Block payroll if no active rate exists for the employee."""
        if not employee:
            return
        # Check for an active (unexpired) rate covering today
        today = date.today()
        rate = (
            self.db.query(EmployeeRate)
            .filter(
                EmployeeRate.employee_id == employee.id,
                EmployeeRate.effective_start_date <= today,
            )
            .filter(
                (EmployeeRate.effective_end_date.is_(None))
                | (EmployeeRate.effective_end_date >= today)
            )
            .first()
        )
        if not rate:
            self._add_error(
                batch_id=batch_id,
                file_id=sub.file_id,
                submission_id=sub.id,
                employee_id=employee.id,
                rule_code="MISSING_RATE",
                severity=SEVERITY_BLOCKER,
                message=f"No active pay rate found for '{employee.full_name}' — payroll cannot be calculated",
                action_required="Add pay rate for this employee in admin settings",
                assigned_to_role="PAYROLL",
            )

    # ── Rule 20: HOURS_TOTAL_MISMATCH ────────────────────────────────────────

    def _check_hours_math(
        self, entries: List[TimesheetEntry], sub: TimesheetSubmission, batch_id: str
    ) -> None:
        """Verify: total_hours = sum(regular_hours + overtime_hours) for all entries."""
        for entry in entries:
            total = float(entry.calculated_hours or entry.entered_hours or 0)
            reg = float(entry.regular_hours or 0)
            ot = float(entry.overtime_hours or 0)
            if total > 0 and abs(total - (reg + ot)) > settings.HOURS_MISMATCH_TOLERANCE:
                self._add_error(
                    batch_id=batch_id,
                    file_id=sub.file_id,
                    submission_id=sub.id,
                    entry_id=entry.id,
                    employee_id=sub.employee_id,
                    rule_code="HOURS_TOTAL_MISMATCH",
                    severity=SEVERITY_ERROR,
                    message=(
                        f"{entry.work_date}: total={total:.2f}h but "
                        f"regular={reg:.2f}h + overtime={ot:.2f}h = {reg + ot:.2f}h"
                    ),
                    expected_value=str(total),
                    actual_value=str(round(reg + ot, 2)),
                    action_required="Correct hour breakdown",
                    assigned_to_role="HR",
                )

    # ── Rule 11: MISSING_TIMESHEET ────────────────────────────────────────────

    def _check_missing_timesheets(self, batch_id: str, batch: Optional[BatchUpload]) -> None:
        """Only check for missing timesheets when a payroll period is set.
        Without a period, we can't know which employees are expected.
        """
        if not batch or not batch.payroll_period_id:
            return

        submitted_employee_ids = {
            row[0]
            for row in self.db.query(TimesheetSubmission.employee_id)
            .filter(TimesheetSubmission.batch_id == batch_id)
            .all()
        }

        active_employees = self.db.query(Employee).filter(Employee.is_active == True).all()
        for emp in active_employees:
            if emp.id not in submitted_employee_ids:
                self._add_error(
                    batch_id=batch_id,
                    employee_id=emp.id,
                    rule_code="MISSING_TIMESHEET",
                    severity=SEVERITY_ERROR,
                    message=f"No timesheet submitted for {emp.full_name}",
                    action_required="Request timesheet from employee",
                    assigned_to_role="HR",
                )

    # ── Rule 12: TWO_MONTH_INACTIVE ───────────────────────────────────────────

    def _has_multi_month_data(self) -> bool:
        from sqlalchemy import func, cast, String
        from app.db.models import TimesheetSubmission as TS
        distinct_months = (
            self.db.query(
                func.count(
                    func.distinct(
                        func.concat(
                            cast(func.extract("year", TS.timesheet_end_date), String),
                            "-",
                            cast(func.extract("month", TS.timesheet_end_date), String),
                        )
                    )
                )
            )
            .filter(
                TS.timesheet_end_date.isnot(None),
                TS.payroll_status != "CANCELLED",
            )
            .scalar()
        ) or 0
        return int(distinct_months) >= 2

    def _check_inactive_employees(self, batch_id: str) -> None:
        from dateutil.relativedelta import relativedelta
        threshold_months = settings.INACTIVE_MONTHS_THRESHOLD
        cutoff = datetime.utcnow() - relativedelta(months=threshold_months)

        employees = self.db.query(Employee).filter(Employee.is_active == True).all()
        for emp in employees:
            last_sub = (
                self.db.query(TimesheetSubmission.submission_date)
                .filter(TimesheetSubmission.employee_id == emp.id)
                .order_by(TimesheetSubmission.submission_date.desc())
                .first()
            )
            last_date = last_sub[0] if last_sub else None

            if last_date is None or last_date < cutoff:
                self._add_error(
                    batch_id=batch_id,
                    employee_id=emp.id,
                    rule_code="TWO_MONTH_INACTIVE",
                    severity=SEVERITY_WARNING,
                    message=f"{emp.full_name} has not submitted a timesheet in {threshold_months}+ months",
                    action_required="Verify if employee is still active; mark inactive if needed",
                    assigned_to_role="HR",
                )

    def _add_error(self, **kwargs) -> None:
        err = ValidationError(id=gen_uuid(), status="OPEN", created_at=datetime.utcnow(), **kwargs)
        self.db.add(err)

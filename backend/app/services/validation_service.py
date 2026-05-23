"""
Validation engine — Phase 7.
All rules are deterministic Python — no LLM involvement.
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
    Vendor, HolidayDate, BatchUpload, gen_uuid,
)

logger = logging.getLogger(__name__)


SEVERITY_BLOCKER = "BLOCKER"
SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"


class ValidationService:
    def __init__(self, db: Session):
        self.db = db

    def validate_batch(self, batch_id: str) -> None:
        """Run all validation rules for every submission in a batch."""
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
        self._check_inactive_employees(batch_id)

        self.db.commit()
        logger.info(f"[{batch_id}] Validation complete for {len(submissions)} submissions")

    def _validate_submission(self, sub: TimesheetSubmission, batch_id: str) -> None:
        entries = (
            self.db.query(TimesheetEntry)
            .filter(TimesheetEntry.submission_id == sub.id)
            .order_by(TimesheetEntry.work_date)
            .all()
        )

        employee = self.db.query(Employee).filter(Employee.id == sub.employee_id).first()
        vendor = self.db.query(Vendor).filter(Vendor.id == sub.vendor_id).first() if sub.vendor_id else None

        has_blockers = False

        # Per-entry rules
        for entry in entries:
            self._check_daily_hours(entry, sub, batch_id)
            self._check_holiday_work(entry, sub, batch_id)

        # Per-week rules
        self._check_weekly_hours(entries, sub, batch_id, vendor)

        # Per-submission rules
        self._check_missing_approval(sub, batch_id)
        self._check_late_submission(sub, batch_id)

        # Determine payroll readiness
        open_blockers = (
            self.db.query(ValidationError)
            .filter(
                ValidationError.submission_id == sub.id,
                ValidationError.severity == SEVERITY_BLOCKER,
                ValidationError.status == "OPEN",
            )
            .count()
        )

        sub.validation_status = "FAILED" if open_blockers else "PASSED"
        sub.payroll_status = "NOT_READY" if open_blockers else "READY"
        sub.updated_at = datetime.utcnow()

    # ── Rule: DAILY_HOURS_EXCEED ───────────────────────────────────────────────

    def _check_daily_hours(
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

    # ── Rule: WEEKLY_HOURS_EXCEED ─────────────────────────────────────────────

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

        weekly_limit = float(vendor.regular_weekly_limit) if vendor else settings.REGULAR_WEEKLY_LIMIT_HOURS
        overtime_allowed = vendor.overtime_enabled if vendor else True

        for week_key, total in weekly.items():
            if total > weekly_limit:
                ot = total - weekly_limit
                severity = SEVERITY_WARNING if overtime_allowed else SEVERITY_BLOCKER
                self._add_error(
                    batch_id=batch_id,
                    file_id=sub.file_id,
                    submission_id=sub.id,
                    employee_id=sub.employee_id,
                    rule_code="WEEKLY_HOURS_EXCEED",
                    severity=severity,
                    message=f"Week {week_key}: {total:.1f}h total, {ot:.1f}h overtime ({'allowed' if overtime_allowed else 'NOT allowed'})",
                    expected_value=str(weekly_limit),
                    actual_value=str(round(total, 2)),
                    action_required="Verify overtime approval" if overtime_allowed else "Overtime not allowed — correct hours",
                    assigned_to_role="HR",
                )

    # ── Rule: HOLIDAY_WORK ────────────────────────────────────────────────────

    def _check_holiday_work(
        self, entry: TimesheetEntry, sub: TimesheetSubmission, batch_id: str
    ) -> None:
        if entry.entry_type != "WORK":
            return
        hours = float(entry.calculated_hours or entry.entered_hours or 0)
        if hours <= 0:
            return

        holiday = (
            self.db.query(HolidayDate)
            .filter(HolidayDate.holiday_date == entry.work_date)
            .first()
        )
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

    # ── Rule: MISSING_APPROVAL ────────────────────────────────────────────────

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

    # ── Rule: LATE_SUBMISSION ─────────────────────────────────────────────────

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
        cutoff = datetime.combine(period.cutoff_date, datetime.min.time())

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

    # ── Rule: MISSING_TIMESHEET ───────────────────────────────────────────────

    def _check_missing_timesheets(self, batch_id: str, batch: Optional[BatchUpload]) -> None:
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

    # ── Rule: TWO_MONTH_INACTIVE ──────────────────────────────────────────────

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

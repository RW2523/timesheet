"""
Payroll service — Phase 9.
Deterministic salary calculation. Never uses LLM.
"""
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import (
    PayrollRun, PayrollResult, TimesheetSubmission, TimesheetEntry,
    Employee, EmployeeRate, Vendor, ValidationError, gen_uuid,
)

logger = logging.getLogger(__name__)


class PayrollService:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, payroll_period_id: str) -> PayrollRun:
        """Create a payroll run for a period. Only includes validated + approved records."""
        submissions = (
            self.db.query(TimesheetSubmission)
            .filter(
                TimesheetSubmission.payroll_period_id == payroll_period_id,
                TimesheetSubmission.payroll_status == "READY",
                TimesheetSubmission.validation_status == "PASSED",
            )
            .all()
        )

        run = PayrollRun(
            id=gen_uuid(),
            payroll_period_id=payroll_period_id,
            run_status="DRAFT",
            total_employees=len(submissions),
            created_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.flush()

        total_reg_hours = Decimal("0")
        total_ot_hours = Decimal("0")
        total_reg_pay = Decimal("0")
        total_ot_pay = Decimal("0")
        ready_count = 0
        blocked_count = 0

        for sub in submissions:
            result = self._calculate_employee_payroll(run.id, sub)
            if result:
                self.db.add(result)
                if result.payroll_status == "READY":
                    total_reg_hours += Decimal(str(result.regular_hours or 0))
                    total_ot_hours += Decimal(str(result.overtime_hours or 0))
                    total_reg_pay += Decimal(str(result.regular_pay or 0))
                    total_ot_pay += Decimal(str(result.overtime_pay or 0))
                    ready_count += 1
                else:
                    blocked_count += 1

        run.total_regular_hours = total_reg_hours
        run.total_overtime_hours = total_ot_hours
        run.total_regular_pay = total_reg_pay
        run.total_overtime_pay = total_ot_pay
        run.total_pay = total_reg_pay + total_ot_pay
        run.payroll_ready_employees = ready_count
        run.blocked_employees = blocked_count
        run.run_status = "FINALIZED" if blocked_count == 0 else "NEEDS_REVIEW"

        self.db.commit()
        logger.info(
            f"Payroll run {run.id} created: {ready_count} ready, {blocked_count} blocked, "
            f"total pay ${float(run.total_pay):,.2f}"
        )
        return run

    def _calculate_employee_payroll(
        self, run_id: str, sub: TimesheetSubmission
    ) -> Optional[PayrollResult]:
        """Calculate payroll for one employee submission. All math is deterministic."""
        entries = (
            self.db.query(TimesheetEntry)
            .filter(TimesheetEntry.submission_id == sub.id)
            .all()
        )

        total_reg = sum(float(e.regular_hours or 0) for e in entries)
        total_ot = sum(float(e.overtime_hours or 0) for e in entries)
        leave_days = sum(1 for e in entries if e.entry_type == "LEAVE")
        holiday_hours = sum(float(e.calculated_hours or 0) for e in entries if e.is_holiday)

        # Get the rate effective during the WORKED period, not today's rate —
        # otherwise a retroactive run or a post-period rate change pays wrong.
        as_of = sub.timesheet_end_date or sub.timesheet_start_date or date.today()
        rate = self._get_rate(sub.employee_id, as_of=as_of)

        if rate is None:
            # Missing rate = payroll blocked
            self._add_blocker(sub, "Missing pay rate for employee")
            return PayrollResult(
                id=gen_uuid(),
                payroll_run_id=run_id,
                employee_id=sub.employee_id,
                vendor_id=sub.vendor_id,
                regular_hours=total_reg,
                overtime_hours=total_ot,
                leave_days=leave_days,
                holiday_hours=holiday_hours,
                payroll_status="BLOCKED",
                notes="Missing pay rate — cannot calculate",
                created_at=datetime.utcnow(),
            )

        reg_rate = float(rate.regular_rate)
        # Overtime = 1.5x if not explicitly set
        ot_rate = float(rate.overtime_rate) if rate.overtime_rate else reg_rate * 1.5

        # Deterministic calculation — never LLM
        regular_pay = round(total_reg * reg_rate, 4)
        overtime_pay = round(total_ot * ot_rate, 4)
        total_pay = round(regular_pay + overtime_pay, 4)

        return PayrollResult(
            id=gen_uuid(),
            payroll_run_id=run_id,
            employee_id=sub.employee_id,
            vendor_id=sub.vendor_id,
            regular_hours=total_reg,
            overtime_hours=total_ot,
            leave_days=leave_days,
            holiday_hours=holiday_hours,
            regular_rate=reg_rate,
            overtime_rate=ot_rate,
            regular_pay=regular_pay,
            overtime_pay=overtime_pay,
            total_pay=total_pay,
            payroll_status="READY",
            created_at=datetime.utcnow(),
        )

    def _get_rate(self, employee_id: str, as_of: Optional[date] = None) -> Optional[EmployeeRate]:
        """Rate effective on ``as_of`` (defaults to today)."""
        as_of = as_of or date.today()
        return (
            self.db.query(EmployeeRate)
            .filter(
                EmployeeRate.employee_id == employee_id,
                EmployeeRate.effective_start_date <= as_of,
            )
            .filter(
                (EmployeeRate.effective_end_date.is_(None))
                | (EmployeeRate.effective_end_date >= as_of)
            )
            .order_by(EmployeeRate.effective_start_date.desc())
            .first()
        )

    def _add_blocker(self, sub: TimesheetSubmission, message: str) -> None:
        err = ValidationError(
            id=gen_uuid(),
            batch_id=sub.batch_id,
            submission_id=sub.id,
            employee_id=sub.employee_id,
            rule_code="MISSING_RATE",
            severity="BLOCKER",
            message=message,
            action_required="Add pay rate in Admin > Employee Rates",
            assigned_to_role="PAYROLL",
            status="OPEN",
            created_at=datetime.utcnow(),
        )
        self.db.add(err)

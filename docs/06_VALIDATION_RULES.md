# Ajace TimeSheet AI Bot — Validation Rules

All validation must be deterministic Python code. The LLM must not make payroll decisions.

## 1. Validation Levels

| Level | Scope |
|---|---|
| File-level | Is file readable, duplicate, supported, timesheet candidate? |
| Submission-level | Does employee/month/approval exist? |
| Entry-level | Are dates, times, and hours valid? |
| Payroll-level | Is salary calculation ready? |

---

## 2. Rule Codes

Use stable rule codes for UI and reports.

```text
FILE_UNSUPPORTED
FILE_DUPLICATE
FILE_OCR_REQUIRED
FILE_PARSE_FAILED
FILE_NON_TIMESHEET
EMPLOYEE_MATCH_REQUIRED
PAYROLL_PERIOD_MISMATCH
DATE_OUTSIDE_PERIOD
DUPLICATE_DATE_ENTRY
OVERLAPPING_DATE_CONFLICT
DAILY_HOURS_MISMATCH
MISSING_IN_TIME
MISSING_OUT_TIME
INVALID_TIME_FORMAT
OUT_TIME_BEFORE_IN_TIME
DAILY_REGULAR_LIMIT_EXCEEDED
WEEKLY_REGULAR_LIMIT_EXCEEDED
OVERTIME_VENDOR_NOT_ELIGIBLE
MONTHLY_OVERTIME_REVIEW
HOLIDAY_ENTRY_MISSING
LEAVE_TYPE_MISSING
LEAVE_OVERLAPS_WORK
APPROVAL_MISSING
APPROVER_MISMATCH
LATE_SUBMISSION
MISSING_TIMESHEET
TWO_MONTH_NO_SUBMISSION
RATE_MISSING
PAYROLL_BLOCKED
```

---

## 3. Daily Hours Validation

The bot must verify:

```text
Calculated Hours = Out-Time - In-Time - Break Time
```

If `entered_hours != calculated_hours`, create error.

Example:

```text
In-Time: 9:00 AM
Out-Time: 5:00 PM
Entered Hours: 7
Calculated Hours: 8
Result: DAILY_HOURS_MISMATCH
```

Tolerance:

- Allow small decimal tolerance, e.g. `0.01`.
- HR can configure tolerance if needed.

Severity:

- `ERROR` if mismatch affects payroll.
- `BLOCKER` if cannot calculate hours.

---

## 4. Daily Regular Limit

Standard regular hours:

```text
Max regular hours per day = 8
```

If worked hours > 8:

- Regular hours = 8.
- Extra hours = overtime only if vendor is overtime eligible.
- If vendor not eligible, flag `OVERTIME_VENDOR_NOT_ELIGIBLE`.

---

## 5. Overtime Rule

Overtime applies only to configured vendors such as NPO.

For eligible vendors:

```text
Overtime Hours = max(0, daily_calculated_hours - 8)
```

For non-eligible vendors:

```text
Overtime Hours = 0
Excess Hours = HR review
```

---

## 6. Weekly Limit Rule

Regular billing hours should not exceed:

```text
40 hours/week
```

If weekly regular hours > 40:

- First 40 = regular hours.
- Excess = overtime only if vendor eligible.
- Otherwise flag HR review.

Week grouping:

- Use Monday-Sunday unless HR config says otherwise.

---

## 7. Monthly Overtime Summary

For overtime-eligible vendors:

```text
Monthly Overtime = sum(all weekly/daily overtime hours in payroll month)
```

Report separately:

- Regular hours.
- Overtime hours.
- Total payable hours.

---

## 8. Holiday Entry Validation

For Ajace internal staff:

- Check HR contract holiday calendar.
- Required paid holidays must appear in the timesheet.
- If a paid holiday is missing, create `HOLIDAY_ENTRY_MISSING`.

Example:

```text
July 4 is a paid holiday.
Timesheet has no July 4 entry.
Result: HOLIDAY_ENTRY_MISSING
```

---

## 9. Leave Validation

Detect and validate:

- PTO.
- Sick leave.
- Unpaid leave.
- Holiday leave.

Rules:

- Leave entry should have leave type.
- Leave should not overlap with work hours for same date unless HR allows it.
- Missing leave type should create `LEAVE_TYPE_MISSING`.

---

## 10. Duplicate and Overlap Validation

Group by:

```text
employee_id + work_date
```

Rules:

| Scenario | Action |
|---|---|
| Same employee, same date, same hours | Duplicate; ignore one or mark duplicate |
| Same employee, same date, different hours | Conflict; HR review |
| Weekly + monthly overlap | Detect duplicate dates |
| Revised timesheet | Compare old/new and require approval |

---

## 11. Payroll Period Validation

Every entry date must belong to the selected payroll period unless explicitly marked as late/correction.

If date outside period:

- Create `DATE_OUTSIDE_PERIOD`.
- Do not include in payroll unless HR approves.

---

## 12. Approval Validation

Timesheet must be approved by client manager before salary processing.

Check:

- Approval status.
- Approver name/email.
- Approval date.
- Whether approver maps to employee/vendor.

If missing:

```text
APPROVAL_MISSING
Payroll Status = BLOCKED
```

---

## 13. Late Submission Rule

If submitted after payroll cutoff date:

- Mark `LATE_SUBMISSION`.
- Move payment to subsequent payroll month.

Example:

```text
March timesheet submitted April 10 after cutoff
→ salary paid in May payroll
```

---

## 14. Missing Timesheet Alerts

After processing a payroll month, compare active employee list against submissions.

If active employee has no timesheet:

```text
MISSING_TIMESHEET
Send reminder
```

---

## 15. Two-Month No Submission Rule

If employee has no timesheet for two consecutive months:

- Mark employee inactive.
- Notify HR.
- Exclude from regular payroll until HR reviews.

Rule code:

```text
TWO_MONTH_NO_SUBMISSION
```

---

## 16. Salary Calculation Rule

Only run after:

- Employee matched.
- Validated hours available.
- Approval present.
- Rate exists.

Formula:

```text
Regular Pay = Regular Hours × Regular Rate
Overtime Pay = Overtime Hours × Overtime Rate
Total Salary = Regular Pay + Overtime Pay
```

If rate missing:

```text
RATE_MISSING
Payroll Status = BLOCKED
```

---

## 17. Validation Output Schema

```json
{
  "rule_code": "DAILY_HOURS_MISMATCH",
  "severity": "ERROR",
  "message": "Entered hours do not match in-time and out-time.",
  "expected_value": "8",
  "actual_value": "7",
  "action_required": "Employee must correct hours or HR must approve override.",
  "assigned_to_role": "HR"
}
```

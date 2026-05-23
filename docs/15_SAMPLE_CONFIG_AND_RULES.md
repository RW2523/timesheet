# Ajace TimeSheet AI Bot — Sample Configuration and Rules

Use this file to seed local development data and rule configuration.

## 1. Vendor Configuration

```json
[
  {
    "name": "NPO",
    "overtime_enabled": true,
    "regular_daily_limit": 8,
    "regular_weekly_limit": 40
  },
  {
    "name": "Ajace Internal",
    "overtime_enabled": false,
    "regular_daily_limit": 8,
    "regular_weekly_limit": 40
  },
  {
    "name": "HCPSS",
    "overtime_enabled": false,
    "regular_daily_limit": 8,
    "regular_weekly_limit": 40
  },
  {
    "name": "Hexaware",
    "overtime_enabled": false,
    "regular_daily_limit": 8,
    "regular_weekly_limit": 40
  },
  {
    "name": "Innosoft",
    "overtime_enabled": false,
    "regular_daily_limit": 8,
    "regular_weekly_limit": 40
  }
]
```

## 2. Payroll Rule Configuration

```json
{
  "default_daily_regular_limit": 8,
  "default_weekly_regular_limit": 40,
  "week_start_day": "MONDAY",
  "hour_tolerance": 0.01,
  "require_client_manager_approval": true,
  "late_submission_moves_to_next_month": true,
  "missing_timesheet_reminder_enabled": true,
  "two_month_no_submission_inactive_enabled": true
}
```

## 3. Employee Type Rules

```json
{
  "AJACE_INTERNAL": {
    "requires_holiday_entries": true,
    "holiday_calendar_required": true
  },
  "CONTRACTOR": {
    "requires_holiday_entries": false
  },
  "CLIENT_VENDOR": {
    "requires_holiday_entries": false
  }
}
```

## 4. File Ignore Rules

Ignore:

```text
desktop.ini
.DS_Store
Thumbs.db
__MACOSX/*
```

## 5. File Alert Rules

```json
{
  "low_pdf_text_chars_threshold": 100,
  "low_ocr_confidence_threshold": 0.70,
  "employee_match_auto_threshold": 0.90,
  "employee_match_review_threshold": 0.70
}
```

## 6. Required Report Sheets

```json
[
  "Batch Summary",
  "File Inventory",
  "Timesheet Entries",
  "Validation Issues",
  "Employee Summary",
  "Vendor Summary",
  "Payroll Ready",
  "ADP Export"
]
```

## 7. Sample Seed Employees

Use fake/dev seed data first. Replace with Ajace real data later.

```json
[
  {
    "employee_code": "EMP001",
    "full_name": "John Smith",
    "email": "john.smith@example.com",
    "vendor": "NPO",
    "employee_type": "CLIENT_VENDOR",
    "regular_rate": 25,
    "overtime_rate": 37.5
  },
  {
    "employee_code": "EMP002",
    "full_name": "Sarah Lee",
    "email": "sarah.lee@example.com",
    "vendor": "Ajace Internal",
    "employee_type": "AJACE_INTERNAL",
    "regular_rate": 30,
    "overtime_rate": null
  }
]
```

## 8. Manual Review Triggers

Require HR review when:

- Employee match confidence < 0.90.
- OCR confidence < 0.70.
- File appears non-timesheet.
- Dates overlap with existing entries.
- File contains dates outside payroll period.
- Approval is missing.
- Holiday entry missing for Ajace internal staff.
- Overtime exists for non-eligible vendor.
- Rate missing.

## 9. Payroll Blocking Rules

Block payroll when:

- Employee is not matched.
- Critical extraction fields are missing.
- Daily hours mismatch is unresolved.
- Approval is missing.
- Employee rate is missing.
- Duplicate conflicting date exists.
- Submission is late and payable period is not current.
- HR has not resolved blocker validation errors.

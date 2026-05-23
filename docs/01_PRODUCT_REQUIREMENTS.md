# Ajace TimeSheet AI Bot — Product Requirements Document

## 1. Product Overview

Ajace needs a full local TimeSheet AI Bot that automates timesheet collection, extraction, validation, review, and payroll report generation.

Employees currently submit timesheets in multiple formats and HR may also collect monthly timesheets in a ZIP folder. Manual processing is slow and error-prone because HR must open many files, calculate hours, check holidays, handle overtime, verify approvals, detect duplicates, and prepare payroll files.

The application must support both:

1. **Bulk HR ZIP upload** for monthly processing.
2. **Future email ingestion** from `timesheets@ajace.com`.

Both input paths must flow into the same common processing engine.

---

## 2. Main Users

### HR User

HR uploads ZIP files, reviews extracted data, resolves employee matching issues, checks validation errors, and exports payroll reports.

### Employee

Employees send timesheets by email in the future phase. They may receive correction or missing-timesheet notifications.

### Client Manager

Client managers approve or reject timesheets before payroll processing.

### Payroll/Admin User

Payroll/Admin reviews final approved records and exports payroll-ready files or ADP-compatible files.

---

## 3. Input Sources

### 3.1 HR ZIP Upload

HR uploads a ZIP file for a selected payroll month. The ZIP may contain nested folders and mixed file types.

The bot must:

- Store the ZIP file.
- Safely unzip it.
- Recursively scan all folders/subfolders.
- Create file inventory records.
- Ignore noise files like `desktop.ini`.
- Detect duplicate files using hashes.
- Infer employee/vendor/month from folder path and filename.
- Process each file using the correct parser/OCR path.

### 3.2 Future Email Ingestion

Employees send timesheets to:

```text
timesheets@ajace.com
```

The bot must later support:

- Reading incoming email.
- Downloading attachments.
- Using the same parser/validation/report pipeline.
- Sending correction/reminder emails.

---

## 4. Supported File Types

The system must support:

| File Type | Required Behavior |
|---|---|
| XLSX/XLS | Read all sheets and detect timesheet tables. |
| CSV | Read rows directly and normalize columns. |
| PDF with text | Extract text/tables using PDF parser. |
| Scanned PDF | Run OCR and layout extraction. |
| PNG/JPG/JPEG | Run OCR. |
| DOCX | Extract text and tables. |
| TXT | Parse simple text. |
| Unknown | Mark unsupported and require HR review. |

---

## 5. Core Features

### 5.1 Batch Upload and Inventory

The application must create a batch record for every uploaded ZIP.

Batch record must show:

- ZIP filename.
- Payroll month/year.
- Upload user.
- Upload timestamp.
- Total files found.
- Processed files.
- Failed files.
- Files needing review.
- Payroll-ready employee count.
- Batch status.

### 5.2 File-Level Processing

For every file, the system must record:

- Folder path.
- File name.
- File extension.
- File size.
- File hash.
- Detected employee name.
- Detected vendor/client.
- Detected payroll period.
- Parser used.
- OCR required flag.
- Duplicate flag.
- Processing status.
- Alerts/errors.

### 5.3 Extraction

The system must extract:

- Employee name.
- Employee ID if available.
- Employee email if available.
- Vendor/client.
- Timesheet period.
- Work date.
- In-time.
- Out-time.
- Break time.
- Entered hours.
- Leave type.
- Holiday entry.
- Approval status.
- Client manager/approver.

### 5.4 Standard JSON Normalization

Every file must be normalized into one common schema regardless of original format.

Example:

```json
{
  "employee_name": "John Smith",
  "employee_id": "EMP001",
  "vendor": "NPO",
  "payroll_month": "2026-04",
  "source_file": "John_Smith_April_2026.xlsx",
  "entries": [
    {
      "date": "2026-04-01",
      "in_time": "09:00",
      "out_time": "17:00",
      "break_minutes": 0,
      "entered_hours": 8,
      "entry_type": "work"
    }
  ],
  "approval": {
    "status": "pending",
    "approver_name": null,
    "approved_at": null
  },
  "extraction_confidence": 0.92,
  "alerts": []
}
```

### 5.5 Employee Matching

The system must match files to employee master data using:

1. Employee ID.
2. Employee email.
3. Exact name.
4. Fuzzy name.
5. HR manual mapping.

Low-confidence matches must be flagged.

### 5.6 Validation

The system must validate all HR rules:

- Daily hours match in-time/out-time.
- Regular hours max 8/day.
- Regular hours max 40/week.
- Overtime only for eligible vendors such as NPO.
- Monthly overtime summary.
- Holiday entries for Ajace internal staff.
- Leave validation.
- Duplicate date detection.
- Old/current month date validation.
- Client manager approval required.
- Late submission after payroll cutoff.
- Missing timesheet reminders.
- Two-month no-submission inactive rule.
- Payroll period retrieval.

### 5.7 Review and Correction

The app must provide HR review screens for:

- Employee match required.
- OCR confidence low.
- Hours mismatch.
- Duplicate dates.
- Missing approval.
- Missing holiday entries.
- Non-timesheet files.
- Unsupported files.
- Payroll blocked records.

### 5.8 Payroll Calculation

Salary must be calculated only after validation and approval.

Formula:

```text
Regular Pay = Regular Hours × Regular Rate
Overtime Pay = Overtime Hours × Overtime Rate
Total Salary = Regular Pay + Overtime Pay
```

Overtime applies only to configured vendors.

### 5.9 Reporting

Generate:

- Batch summary.
- File inventory report.
- Validation exception report.
- Employee monthly summary.
- Vendor monthly summary.
- Payroll-ready Excel.
- ADP-compatible export.

---

## 6. Product Status Lifecycle

### Batch Status

```text
UPLOADED
UNZIPPING
SCANNING
PROCESSING
VALIDATING
NEEDS_REVIEW
REPORT_READY
COMPLETED
FAILED
```

### File Status

```text
DETECTED
IGNORED
DUPLICATE
PARSING
OCR_REQUIRED
OCR_COMPLETED
EXTRACTED
EMPLOYEE_MATCHED
MATCH_REVIEW_REQUIRED
VALIDATED
VALIDATION_FAILED
PAYROLL_READY
PAYROLL_BLOCKED
UNSUPPORTED
FAILED
```

### Timesheet Status

```text
RECEIVED
EXTRACTED
VALIDATION_PASSED
VALIDATION_FAILED
PENDING_CORRECTION
PENDING_MANAGER_APPROVAL
APPROVED
PAYROLL_READY
PAYROLL_EXPORTED
CLOSED
```

---

## 7. Non-Functional Requirements

- Full local deployment.
- No cloud dependency for core processing.
- Docker Compose for local orchestration.
- PostgreSQL for reliable relational storage.
- Redis/Celery for background processing.
- All processing must be auditable.
- Original files must be retained.
- Raw extraction must be retained.
- Manual HR override must be recorded.
- No payroll export without validation/approval.
- Failed files must not block the whole batch.
- System must handle large ZIPs using background jobs.

---

## 8. Final Problem Statement

Ajace needs a robust local TimeSheet AI Bot that can process employee timesheets from bulk ZIP uploads and future email submissions. The bot must read multiple file formats, extract timesheet rows, understand nested folder structures, match files to employees, validate all HR/payroll rules, flag issues for HR review, calculate approved hours and salary, and generate payroll-ready Excel or ADP-compatible exports.

The system must be generic, auditable, fault-tolerant, and powerful enough to handle scanned PDFs, images, Excel files, DOCX files, CSV files, duplicate files, partial-period files, missing approvals, late submissions, missing holiday entries, and vendor-specific overtime rules.

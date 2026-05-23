# Ajace TimeSheet AI Bot — Testing and Acceptance Criteria

## 1. Testing Strategy

Test in layers:

1. Unit tests for validation rules.
2. Unit tests for parsers.
3. Integration tests for ZIP upload pipeline.
4. Worker tests for batch processing.
5. API tests for backend endpoints.
6. UI tests for HR dashboard flows.
7. End-to-end tests using sample ZIP.

---

## 2. Parser Test Cases

Test files:

- Clear Excel timesheet.
- CSV timesheet.
- DOCX timesheet with table.
- Text PDF.
- Scanned PDF.
- PNG/JPG timesheet.
- Unsupported file.
- Empty file.
- Non-timesheet file.

Expected:

- No crash.
- File status correct.
- Raw extraction saved.
- Alerts created where required.

---

## 3. ZIP Test Cases

The sample ZIP taught these cases:

- Nested folders.
- Vendor folders.
- Mixed file types.
- Duplicate files.
- `desktop.ini` files.
- Images requiring OCR.
- Scanned PDFs requiring OCR.
- Partial weekly files.
- Semi-monthly files.
- Monthly files.
- Non-timesheet document.

Acceptance:

- ZIP is processed completely.
- All files appear in inventory.
- Noise files ignored.
- Duplicate files flagged.
- OCR-required files flagged or OCR processed.
- Non-timesheet files flagged.
- Processing continues after bad files.

---

## 4. Validation Test Cases

### Daily Hours

Input:

```text
9:00 AM - 5:00 PM, entered 7 hours
```

Expected:

```text
DAILY_HOURS_MISMATCH
```

### Overtime Eligible Vendor

Input:

```text
NPO employee works 10 hours
```

Expected:

```text
regular_hours=8
overtime_hours=2
```

### Overtime Non-Eligible Vendor

Input:

```text
Non-NPO employee works 10 hours
```

Expected:

```text
OVERTIME_VENDOR_NOT_ELIGIBLE
payroll blocked or HR review
```

### Weekly Limit

Input:

```text
45 regular hours in week
```

Expected:

```text
40 regular hours
5 overtime if eligible else HR review
```

### Holiday Missing

Input:

```text
Ajace internal staff missing July 4 holiday entry
```

Expected:

```text
HOLIDAY_ENTRY_MISSING
```

### Approval Missing

Expected:

```text
APPROVAL_MISSING
PAYROLL_BLOCKED
```

### Late Submission

Expected:

```text
LATE_SUBMISSION
payable period moved to next payroll
```

### Missing Timesheet

Expected:

```text
MISSING_TIMESHEET
notification created
```

### Two Months Missing

Expected:

```text
TWO_MONTH_NO_SUBMISSION
employee marked inactive
HR notification created
```

---

## 5. Payroll Test Cases

Payroll must not calculate when:

- Employee is not matched.
- Validation blockers exist.
- Approval is missing.
- Rate is missing.

Payroll must calculate when:

- Employee matched.
- Validated entries available.
- Approval present.
- Rate present.
- Correct payable period.

---

## 6. Report Acceptance Criteria

Generated workbook must include:

- Batch Summary.
- File Inventory.
- Timesheet Entries.
- Validation Issues.
- Employee Summary.
- Vendor Summary.
- Payroll Ready.
- ADP Export.

Report must:

- Open in Excel.
- Have headers.
- Have filters.
- Highlight errors/blockers.
- Contain totals.

---

## 7. UI Acceptance Criteria

HR must be able to:

- Upload ZIP.
- View processing status.
- View all files.
- See alerts.
- See validation issues.
- Download reports.
- Reprocess a file or batch.
- Manually assign employee.
- Resolve validation issue.

---

## 8. Non-Crash Requirement

The application must not fail the entire batch because of one bad file.

Bad file behavior:

- Mark file failed.
- Save error.
- Continue processing.
- Show issue in HR dashboard.

---

## 9. Definition of Done for MVP

MVP is done when:

1. HR can upload a ZIP.
2. App unzips and scans nested folders.
3. File inventory is created.
4. Excel/CSV/DOCX/text PDF files are parsed.
5. Scanned/image files are flagged or OCRed.
6. Employee matching is attempted.
7. Timesheet rows are normalized.
8. Validation rules run.
9. Reports are generated.
10. HR can download Excel report.

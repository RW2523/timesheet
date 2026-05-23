# Ajace TimeSheet AI Bot — API Specification

Base URL:

```text
/api/v1
```

## 1. Upload APIs

### POST `/batches/upload-zip`

Upload monthly ZIP.

Request:

```multipart/form-data
file: ZIP
payroll_period_id: UUID
notes: optional string
```

Response:

```json
{
  "batch_id": "uuid",
  "status": "UPLOADED",
  "message": "ZIP uploaded and processing job started."
}
```

### POST `/batches/{batch_id}/reprocess`

Reprocess a batch.

Response:

```json
{
  "batch_id": "uuid",
  "status": "PROCESSING"
}
```

---

## 2. Batch APIs

### GET `/batches`

List batches.

Query params:

- `status`
- `payroll_period_id`
- `page`
- `limit`

### GET `/batches/{batch_id}`

Get batch summary.

Response:

```json
{
  "id": "uuid",
  "source_type": "ZIP_UPLOAD",
  "source_name": "April_2026_Timesheets.zip",
  "status": "NEEDS_REVIEW",
  "total_files": 62,
  "processed_files": 45,
  "failed_files": 3,
  "review_required_files": 10,
  "payroll_ready_count": 40
}
```

### GET `/batches/{batch_id}/progress`

Return live progress.

```json
{
  "batch_id": "uuid",
  "status": "PROCESSING",
  "current_stage": "OCR",
  "processed_files": 21,
  "total_files": 62,
  "percent": 34
}
```

---

## 3. File Inventory APIs

### GET `/batches/{batch_id}/files`

List files in batch.

Filters:

- `processing_status`
- `match_status`
- `ocr_required`
- `is_duplicate`
- `is_timesheet_candidate`

Response item:

```json
{
  "file_id": "uuid",
  "folder_path": "NPO/April",
  "file_name": "John_Smith_April_2026.xlsx",
  "file_ext": ".xlsx",
  "detected_employee_name": "John Smith",
  "detected_vendor_name": "NPO",
  "matched_employee_id": "uuid",
  "processing_status": "VALIDATED",
  "alerts": []
}
```

### GET `/files/{file_id}`

Get file detail, raw extraction summary, and alerts.

### POST `/files/{file_id}/mark-non-timesheet`

HR marks a file as non-timesheet.

### POST `/files/{file_id}/assign-employee`

Manual employee match.

Request:

```json
{
  "employee_id": "uuid"
}
```

---

## 4. Extraction APIs

### GET `/files/{file_id}/raw-extraction`

Returns raw text, tables, and LLM JSON.

### POST `/files/{file_id}/reextract`

Re-run parser/OCR/LLM extraction for one file.

---

## 5. Timesheet Entry APIs

### GET `/batches/{batch_id}/entries`

List extracted normalized timesheet rows.

Filters:

- employee_id
- validation_status
- work_date_from
- work_date_to

### PATCH `/entries/{entry_id}`

HR correction/override.

Request:

```json
{
  "in_time": "09:00",
  "out_time": "17:00",
  "entered_hours": 8,
  "leave_type": null,
  "override_reason": "Corrected after HR review"
}
```

All edits must create audit log.

---

## 6. Validation APIs

### GET `/batches/{batch_id}/validation-errors`

List validation errors.

Filters:

- severity
- status
- rule_code
- employee_id

### POST `/validation-errors/{error_id}/resolve`

Resolve validation error.

Request:

```json
{
  "resolution_note": "Employee submitted corrected file."
}
```

### POST `/batches/{batch_id}/run-validation`

Run validation again for a batch.

---

## 7. Approval APIs

### GET `/submissions/pending-approval`

List submissions pending client manager approval.

### POST `/submissions/{submission_id}/approve`

Mark approved.

Request:

```json
{
  "approver_name": "Client Manager Name",
  "approver_email": "manager@example.com",
  "approval_date": "2026-04-30T12:00:00Z",
  "notes": "Approved by email"
}
```

### POST `/submissions/{submission_id}/reject`

Mark rejected.

---

## 8. Payroll APIs

### POST `/payroll-runs`

Create payroll run for a payroll period.

Request:

```json
{
  "payroll_period_id": "uuid"
}
```

### GET `/payroll-runs/{payroll_run_id}`

Get payroll summary.

### GET `/payroll-runs/{payroll_run_id}/results`

List employee payroll results.

### POST `/payroll-runs/{payroll_run_id}/generate-report`

Generate payroll Excel report.

---

## 9. Report APIs

### GET `/batches/{batch_id}/reports`

List generated reports.

### GET `/reports/{report_id}/download`

Download report file.

Report types:

```text
FILE_INVENTORY
VALIDATION_EXCEPTIONS
TIMESHEET_ENTRIES
EMPLOYEE_MONTHLY_SUMMARY
VENDOR_MONTHLY_SUMMARY
PAYROLL_READY
ADP_EXPORT
```

---

## 10. Admin APIs

### Employee APIs

```text
GET    /employees
POST   /employees
GET    /employees/{employee_id}
PATCH  /employees/{employee_id}
```

### Vendor APIs

```text
GET    /vendors
POST   /vendors
PATCH  /vendors/{vendor_id}
```

### Rate APIs

```text
GET    /employee-rates
POST   /employee-rates
PATCH  /employee-rates/{rate_id}
```

### Holiday APIs

```text
GET    /holiday-calendars
POST   /holiday-calendars
POST   /holiday-calendars/{calendar_id}/dates
```

### Payroll Period APIs

```text
GET    /payroll-periods
POST   /payroll-periods
PATCH  /payroll-periods/{period_id}
```

---

## 11. Health APIs

### GET `/health`

```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok"
}
```

### GET `/worker-health`

Returns worker status.

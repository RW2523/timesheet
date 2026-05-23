# Ajace TimeSheet AI Bot — Frontend Requirements

Use Next.js + TypeScript + Tailwind CSS.

## 1. Frontend Pages

### 1. Dashboard

Show:

- Total batches.
- Active processing batches.
- Batches needing review.
- Payroll-ready batches.
- Missing timesheets.
- Validation blockers.

### 2. ZIP Upload Page

Fields:

- Payroll month/period.
- ZIP file upload.
- Optional notes.

After upload:

- Show batch ID.
- Show progress.
- Navigate to batch detail.

### 3. Batch Detail Page

Show:

- Batch summary cards.
- Progress bar.
- File status counts.
- Validation status counts.
- Reports generated.

### 4. File Inventory Page

Table columns:

- Folder path.
- File name.
- File type.
- Detected employee.
- Matched employee.
- Vendor/client.
- OCR required.
- Duplicate flag.
- Status.
- Alerts.
- Actions.

Actions:

- View raw extraction.
- Assign employee.
- Mark non-timesheet.
- Reprocess file.

### 5. Employee Match Review Page

Show low-confidence matches.

Actions:

- Confirm match.
- Change employee.
- Create employee placeholder.
- Mark file as non-timesheet.

### 6. Extracted Entries Page

Table columns:

- Employee.
- Work date.
- In-time.
- Out-time.
- Break.
- Entered hours.
- Calculated hours.
- Regular hours.
- Overtime hours.
- Leave type.
- Holiday.
- Validation status.

Actions:

- Edit row.
- Add note.
- Resolve issue.

### 7. Validation Issues Page

Table columns:

- Severity.
- Rule code.
- Employee.
- File.
- Date.
- Message.
- Expected.
- Actual.
- Action required.
- Status.

Actions:

- Resolve.
- Reprocess file.
- Assign to HR/employee/manager.

### 8. Approval Page

Show:

- Pending approvals.
- Approved submissions.
- Missing approvals.
- Approver mismatch.

Actions:

- Mark approved.
- Mark rejected.
- Add approver details.

### 9. Payroll Summary Page

Show:

- Payroll period.
- Employee count.
- Payroll-ready count.
- Blocked count.
- Regular hours.
- Overtime hours.
- Total pay.

Actions:

- Generate payroll report.
- Download Excel.
- Download ADP export.

### 10. Admin Settings Page

Tabs:

- Employees.
- Vendors.
- Client managers.
- Employee rates.
- Holiday calendars.
- Payroll periods.
- Validation rules.

---

## 2. UI Components

Create reusable components:

- `StatusBadge`
- `SeverityBadge`
- `DataTable`
- `FileUploadBox`
- `ProgressBar`
- `BatchSummaryCards`
- `ValidationIssuePanel`
- `EmployeeMatchModal`
- `RawExtractionViewer`
- `ReportDownloadList`

---

## 3. UX Rules

- HR should always know why payroll is blocked.
- Every error should show action required.
- Low-confidence extraction should be visually highlighted.
- Duplicate files should not be hidden; show them as ignored/duplicate.
- Manual corrections must ask for override reason.
- Report download should be available only after report generation.

---

## 4. Batch Detail Layout

```text
[Batch Header]
ZIP: April_2026_Timesheets.zip
Status: NEEDS_REVIEW
Payroll Month: April 2026

[Summary Cards]
Total Files | Processed | Needs Review | Failed | Payroll Ready | Blocked

[Tabs]
Files | Entries | Validation Issues | Approvals | Payroll | Reports
```

---

## 5. Frontend API Client

Create typed API client:

```text
src/lib/api.ts
src/types/batch.ts
src/types/file.ts
src/types/timesheet.ts
src/types/validation.ts
src/types/report.ts
```

---

## 6. Required Frontend States

Handle:

- Loading.
- Empty results.
- API error.
- Processing in progress.
- Review required.
- Report ready.
- File upload failure.

---

## 7. MVP UI Scope

First build these screens:

1. Dashboard.
2. ZIP Upload.
3. Batch Detail.
4. File Inventory.
5. Validation Issues.
6. Report Download.

Then add employee matching, entry editing, approval, and admin settings.

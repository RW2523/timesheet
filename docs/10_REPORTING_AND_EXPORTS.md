# Ajace TimeSheet AI Bot — Reporting and Exports

Use pandas + openpyxl for Excel generation.

## 1. Report Types

The system must generate:

1. File Inventory Report.
2. Raw Extraction Summary Report.
3. Validation Exception Report.
4. Timesheet Entry Report.
5. Employee Monthly Summary.
6. Vendor Monthly Summary.
7. Payroll Ready Report.
8. ADP-Compatible Export.

---

## 2. File Inventory Report

Columns:

- Batch ID.
- ZIP file name.
- Folder path.
- File name.
- File type.
- File size.
- File hash.
- Detected employee name.
- Matched employee.
- Vendor/client.
- Payroll period detected.
- OCR required.
- Duplicate flag.
- Timesheet candidate flag.
- Parser used.
- Processing status.
- Alerts.

---

## 3. Validation Exception Report

Columns:

- Severity.
- Rule code.
- Employee ID.
- Employee name.
- Vendor.
- File name.
- Work date.
- Message.
- Expected value.
- Actual value.
- Action required.
- Assigned role.
- Status.

---

## 4. Timesheet Entry Report

Columns:

- Employee ID.
- Employee name.
- Vendor/client.
- Source file.
- Work date.
- Day of week.
- In-time.
- Out-time.
- Break minutes.
- Entered hours.
- Calculated hours.
- Regular hours.
- Overtime hours.
- Entry type.
- Leave type.
- Holiday flag.
- Holiday name.
- Approval status.
- Validation status.

---

## 5. Employee Monthly Summary

Columns:

- Employee ID.
- Employee name.
- Vendor/client.
- Payroll month.
- Total regular hours.
- Total overtime hours.
- Total leave days.
- Total holiday hours.
- Missing days count.
- Late submission status.
- Approval status.
- Validation status.
- Payroll readiness.

---

## 6. Vendor Monthly Summary

Columns:

- Vendor/client.
- Payroll month.
- Employee count.
- Total regular hours.
- Total overtime hours.
- Overtime eligible.
- Payroll-ready employees.
- Blocked employees.
- Total regular pay.
- Total overtime pay.
- Total pay.

---

## 7. Payroll Ready Report

Only include employees who are:

- Matched.
- Validated.
- Approved.
- Have rates configured.
- Not blocked by late submission rules unless payable period is correct.

Columns:

- Employee ID.
- Employee name.
- Vendor/client.
- Payroll period.
- Payable period.
- Regular hours.
- Overtime hours.
- Regular rate.
- Overtime rate.
- Regular pay.
- Overtime pay.
- Total pay.
- Notes.

---

## 8. ADP-Compatible Export

Start with generic ADP-compatible XLSX/CSV. Do not directly submit to ADP in MVP.

Columns may include:

- Employee ID.
- Pay period start.
- Pay period end.
- Earnings code.
- Regular hours.
- Overtime hours.
- Department.
- Location.
- Pay amount.

Make the exact ADP format configurable after HR confirms import requirements.

---

## 9. Excel Workbook Structure

Generate one workbook with multiple sheets:

```text
01_Batch_Summary
02_File_Inventory
03_Timesheet_Entries
04_Validation_Issues
05_Employee_Summary
06_Vendor_Summary
07_Payroll_Ready
08_ADP_Export
```

---

## 10. Styling Requirements

Use openpyxl to:

- Freeze header rows.
- Auto-adjust column widths.
- Bold headers.
- Add filters.
- Highlight blockers/errors.
- Add summary totals.

---

## 11. Report Generation Timing

Reports should be generated:

- After batch processing.
- After validation rerun.
- After HR manual corrections.
- After payroll run creation.

---

## 12. Report Storage

Save reports to:

```text
/storage/reports/{batch_id}/ajace_timesheet_report_{payroll_period}.xlsx
/storage/reports/{batch_id}/adp_export_{payroll_period}.csv
```

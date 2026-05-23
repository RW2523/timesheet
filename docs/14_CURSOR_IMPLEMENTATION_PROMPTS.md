# Ajace TimeSheet AI Bot — Cursor Implementation Prompts

Use these prompts phase by phase inside Cursor.

---

## Prompt 1 — Create Project Skeleton

```text
Read all markdown files in this docs folder. Create a monorepo for the Ajace TimeSheet AI Bot with frontend, backend, Docker Compose, PostgreSQL, Redis, and Celery worker. Use Next.js + TypeScript + Tailwind for frontend and FastAPI + SQLAlchemy/SQLModel for backend. Implement health endpoints and a working docker compose setup. Do not implement business logic yet. Follow the architecture and database docs exactly.
```

---

## Prompt 2 — Implement Database Models

```text
Implement the PostgreSQL database models and Alembic migrations based on 03_DATABASE_SCHEMA.md. Use UUID primary keys, timestamps, and enums/check constraints where practical. Create SQLAlchemy/SQLModel models for users, employees, vendors, payroll periods, batch uploads, uploaded files, raw extractions, timesheet submissions, timesheet entries, validation errors, approval records, payroll runs, payroll results, generated reports, notification logs, and audit logs.
```

---

## Prompt 3 — Build ZIP Upload and Batch API

```text
Implement ZIP upload API POST /api/v1/batches/upload-zip. Save the uploaded ZIP into /storage/uploads/{batch_id}/original.zip, create a batch_uploads row, enqueue a Celery process_batch_task, and return batch_id. Also implement GET /batches, GET /batches/{batch_id}, and GET /batches/{batch_id}/progress.
```

---

## Prompt 4 — Build Safe Unzip and File Inventory

```text
Implement safe ZIP extraction and recursive file scanning. Prevent path traversal. Ignore desktop.ini, .DS_Store, Thumbs.db, and __MACOSX. For every valid file, compute SHA256 hash, capture folder path, extension, size, file name, and create uploaded_files records. Detect exact duplicate files by hash and mark duplicates. Infer possible employee name, vendor, and period from folder path and file name. Update batch totals.
```

---

## Prompt 5 — Build File Inventory UI

```text
Implement frontend ZIP upload page, batch list page, batch detail page, and file inventory table. Show batch status, progress, file counts, duplicate files, ignored files, OCR-required files, failed files, and review-required files. Add actions for view file details and reprocess file placeholders.
```

---

## Prompt 6 — Implement Basic Parsers

```text
Implement parser_router.py and parsers for Excel, CSV, DOCX, and text PDFs. Excel/CSV should use pandas/openpyxl. DOCX should use python-docx. PDFs should use PyMuPDF/pdfplumber. Store raw extraction results in raw_extractions. Mark unsupported files and parser failures without crashing the batch.
```

---

## Prompt 7 — Implement OCR Pipeline

```text
Implement OCR detection and OCR pipeline. For PDFs, detect low text layer and mark OCR_REQUIRED. Add image OCR for PNG/JPG/JPEG using PaddleOCR if available and Tesseract fallback. Add scanned PDF OCR support. Store OCR text, confidence, warnings, and metadata in raw_extractions. If OCR fails, mark file OCR_FAILED and create validation alert.
```

---

## Prompt 8 — Implement Standard JSON Normalizer

```text
Implement a normalizer that converts raw extraction results into the standard timesheet JSON schema from 05_EXTRACTION_OCR_LLM_DESIGN.md. First support deterministic column mapping for clear Excel/CSV tables. Add an LLMService interface for messy extraction cleanup, but keep it optional with LLM_ENABLED=false. Validate normalized JSON with Pydantic. Low confidence records must require HR review.
```

---

## Prompt 9 — Implement Employee Matching

```text
Implement employee matching using employee_id, email, exact full name, then fuzzy name matching with rapidfuzz. Use thresholds >=0.90 auto-match, 0.70-0.89 review suggested, <0.70 manual review required. Save employee_file_matches and update uploaded_files match status. Add API and UI for manual employee assignment.
```

---

## Prompt 10 — Create Timesheet Submissions and Entries

```text
Create timesheet_submissions and timesheet_entries from normalized JSON. Each file should create or link to a submission. Each date row should become a timesheet_entries row. Preserve row_source JSON. Group by employee and payroll period. Detect weekly/semi-monthly/monthly partial files and support merging at validation/report time.
```

---

## Prompt 11 — Implement Validation Engine

```text
Implement rule-based validation using 06_VALIDATION_RULES.md. Add daily hours validation, missing in/out time, invalid time format, daily 8-hour regular limit, weekly 40-hour limit, vendor-specific overtime, holiday validation for Ajace internal staff, leave validation, duplicate date validation, approval validation, late submission validation, missing timesheet detection, two-month no-submission inactive rule, and missing rate validation. Save validation_errors with severity and action_required.
```

---

## Prompt 12 — Implement Validation UI

```text
Implement validation issues page. Show severity, rule code, employee, file, work date, message, expected value, actual value, action required, and status. Add filters by severity, rule code, employee, and status. Add resolve action with resolution note and audit logging.
```

---

## Prompt 13 — Implement Report Generation

```text
Implement report generation using pandas and openpyxl. Generate a multi-sheet Excel workbook with Batch Summary, File Inventory, Timesheet Entries, Validation Issues, Employee Summary, Vendor Summary, Payroll Ready, and ADP Export sheets. Apply filters, freeze headers, format columns, and highlight blockers/errors. Save report path in generated_reports and provide download API.
```

---

## Prompt 14 — Implement Payroll Calculation

```text
Implement payroll calculation. Only include submissions that are employee-matched, validation-passed or non-blocked, approved, have valid employee rate, and belong to correct payable period. Calculate regular pay, overtime pay, and total pay. Overtime applies only to eligible vendors. Missing approval/rate/validation blockers must exclude employee from payroll-ready report.
```

---

## Prompt 15 — Final E2E Testing

```text
Create tests and seed data to validate the full pipeline. Test ZIP upload, nested folders, duplicate files, desktop.ini ignore, Excel/CSV/DOCX/PDF parsing, OCR-required flag, employee matching, validation rules, payroll blocking, report generation, and download. Ensure one bad file does not fail the entire batch.
```

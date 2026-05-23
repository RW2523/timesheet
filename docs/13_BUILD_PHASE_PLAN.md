# Ajace TimeSheet AI Bot — Build Phase Plan

Build the application in phases. Do not start with all AI/OCR features at once.

## Phase 0 — Repository Setup

Deliverables:

- Monorepo folder structure.
- Docker Compose.
- Backend FastAPI app.
- Frontend Next.js app.
- PostgreSQL connection.
- Redis/Celery connection.
- Health endpoints.

Acceptance:

- `docker compose up` starts all MVP services.
- `/health` returns OK.
- Frontend loads.

---

## Phase 1 — ZIP Upload and File Inventory

Deliverables:

- ZIP upload API.
- Safe ZIP extraction.
- Recursive folder scanner.
- File metadata capture.
- Hash duplicate detection.
- Noise file ignore.
- File inventory dashboard.

Acceptance:

- HR uploads ZIP.
- All files appear in inventory.
- `desktop.ini` ignored.
- Duplicate files flagged.

---

## Phase 2 — Basic Parsers

Deliverables:

- Excel parser.
- CSV parser.
- DOCX parser.
- PDF text parser.
- Raw extraction storage.

Acceptance:

- Structured files produce raw extraction records.
- Unsupported files are flagged.
- Batch continues after failed files.

---

## Phase 3 — OCR and Layout Extraction

Deliverables:

- OCR-required detection for PDFs.
- Image OCR pipeline.
- Scanned PDF OCR pipeline.
- Docling/PaddleOCR integration.
- Tesseract fallback.

Acceptance:

- Image timesheets produce OCR text.
- Scanned PDFs are processed or flagged.
- OCR confidence is stored.

---

## Phase 4 — Standard JSON Normalization

Deliverables:

- Standard timesheet JSON schema.
- Deterministic mapping for clear tables.
- LLM cleanup interface.
- Strict JSON validation.
- Low-confidence review flag.

Acceptance:

- Parsed/OCR data becomes normalized JSON.
- Missing fields use null.
- Invalid LLM JSON does not crash pipeline.

---

## Phase 5 — Employee Matching

Deliverables:

- Employee master table.
- Vendor table.
- Client manager table.
- Exact/fuzzy matching.
- Manual match UI.

Acceptance:

- Exact matches auto-match.
- Low-confidence matches require HR review.
- Manual assignment creates audit log.

---

## Phase 6 — Timesheet Entries and Merging

Deliverables:

- Create timesheet submissions.
- Create timesheet entries.
- Merge weekly/semi-monthly/monthly records.
- Detect overlapping dates.
- Detect old dates mixed with new period.

Acceptance:

- Same employee/month is grouped.
- Duplicate dates detected.
- Conflicting dates flagged.

---

## Phase 7 — Validation Engine

Deliverables:

- Daily hours validation.
- Weekly 40-hour validation.
- Overtime rules.
- Holiday validation.
- Leave validation.
- Approval validation.
- Late submission validation.
- Missing timesheet detection.
- Two-month inactive rule.

Acceptance:

- Each rule creates validation_errors.
- Payroll blocked when blockers exist.
- HR can view issues.

---

## Phase 8 — Reports

Deliverables:

- File inventory report.
- Timesheet entries report.
- Validation exceptions report.
- Employee summary.
- Vendor summary.
- Payroll-ready report.

Acceptance:

- Excel workbook downloads successfully.
- Error rows are highlighted.
- Totals are accurate.

---

## Phase 9 — Payroll Calculation

Deliverables:

- Employee rates.
- Salary calculation.
- Payroll run creation.
- ADP-compatible export.

Acceptance:

- Only validated and approved records included.
- Missing rates block payroll.
- Regular/overtime pay calculated correctly.

---

## Phase 10 — Future Email Integration

Deliverables:

- Email inbox connection.
- Attachment download.
- Email metadata storage.
- Same common processing pipeline.
- Reminder/correction emails.

Acceptance:

- Email attachments process same as ZIP files.

---

## Build Priority Summary

Start with:

```text
Docker + FastAPI + PostgreSQL + Redis + ZIP upload + file inventory
```

Then add:

```text
Parsers → OCR → JSON normalization → validation → reports → payroll
```

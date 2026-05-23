# Ajace TimeSheet AI Bot — Cursor Master Build Prompt

Use this file as the first instruction document in Cursor. Read every `.md` file in this folder before writing code.

## Goal

Build a full local, end-to-end TimeSheet AI Bot for Ajace. The application must process employee timesheets from two input sources:

1. HR bulk ZIP upload containing monthly timesheets in nested folders.
2. Future email ingestion from `timesheets@ajace.com`.

The system must handle mixed file formats, extract timesheet data, validate all HR/payroll rules, highlight issues, support HR review, and generate payroll-ready Excel reports.

## Must-Have Input Support

The application must support:

- ZIP files with nested folders/subfolders.
- PDF files with text layer.
- Scanned PDFs requiring OCR.
- Images: PNG, JPG, JPEG.
- Excel: XLSX, XLS.
- CSV.
- DOCX.
- Email body text in a future phase.
- Unknown/unsupported files should not crash the system; they should be flagged for HR review.

## Core Product Rule

Never allow an LLM to directly calculate salary or make final payroll decisions.

The LLM may help with:

- Messy extraction cleanup.
- Understanding folder/file names.
- Converting OCR output to strict JSON.
- Explaining validation issues.
- Employee matching assistance when confidence is low.

The following must be deterministic Python code:

- Daily hours calculation.
- Weekly regular-hour limit.
- Overtime logic.
- Holiday validation.
- Late submission rule.
- Missing timesheet detection.
- Duplicate detection.
- Salary calculation.
- Payroll report generation.

## Target Local Stack

Build as a full local Docker Compose application:

- Frontend: Next.js + TypeScript + Tailwind CSS.
- Backend: Python FastAPI.
- Database: PostgreSQL.
- Queue: Redis + Celery.
- Worker: Python worker for ZIP processing, parsing, OCR, LLM cleanup, validation, and report generation.
- File storage: Local mounted volume first; MinIO optional later.
- OCR: PaddleOCR + Docling, with Tesseract fallback.
- Document parsers: PyMuPDF, pdfplumber, pandas, openpyxl, python-docx, Pillow.
- LLM: TensorRT-LLM on DGX Spark, preferred model `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4`; optional helper `nvidia/Qwen3-14B-FP4`; optional review model `nvidia/Qwen3-32B-FP4`.
- Reports: pandas + openpyxl.

## Build Method

Build phase by phase. Do not try to implement all AI/OCR complexity at once.

Recommended implementation sequence:

1. Project skeleton with Docker Compose.
2. PostgreSQL schema and migrations.
3. ZIP upload API and local file storage.
4. Safe unzip + recursive file inventory.
5. Duplicate detection and file type classification.
6. Parser router with basic Excel/CSV/DOCX/PDF text extraction.
7. OCR pipeline for scanned PDFs/images.
8. Standard timesheet JSON normalization.
9. Employee matching engine.
10. Rule-based validation engine.
11. HR dashboard and review tables.
12. Excel report generation.
13. Payroll calculation.
14. ADP-compatible export.
15. Future email ingestion.

## Non-Negotiable Behaviors

- Do not crash on bad files.
- Store original files and extracted text.
- Keep raw extraction separate from clean normalized records.
- Every file must have a processing status.
- Every validation issue must be saved with severity and action required.
- Duplicate files must be detected using file hash.
- Duplicate dates for the same employee must be detected.
- Partial weekly/semi-monthly/monthly files for one employee must be merged carefully.
- Payroll must use only approved and validated timesheets.
- Late submissions must be moved to the subsequent payroll cycle.
- Missing submissions must trigger reminders.
- Two months of no submission should mark employee inactive and notify HR.

## Required Output

The app must generate:

- Batch upload summary.
- File inventory table.
- Extracted timesheet entry table.
- Validation exception report.
- Employee-level monthly summary.
- Vendor-level monthly summary.
- Payroll-ready Excel report.
- ADP-compatible CSV/XLSX export.

## Important Sample ZIP Lessons

The sample ZIP had these real-world issues:

- Nested folders by vendor/client.
- Many PDFs.
- Several scanned PDFs requiring OCR.
- Image timesheets requiring OCR.
- Excel files.
- DOCX files.
- CSV file.
- `desktop.ini` noise files.
- Duplicate file paths/hash.
- Weekly, semi-monthly, and monthly timesheets mixed together.
- Non-timesheet document such as reimbursement PDF.
- Inconsistent employee names in filenames.

The system must be generic enough to handle all of these.

## Cursor Instruction

Before coding, read these files in order:

1. `01_PRODUCT_REQUIREMENTS.md`
2. `02_SYSTEM_ARCHITECTURE.md`
3. `03_DATABASE_SCHEMA.md`
4. `04_PROCESSING_PIPELINE.md`
5. `05_EXTRACTION_OCR_LLM_DESIGN.md`
6. `06_VALIDATION_RULES.md`
7. `07_API_SPEC.md`
8. `08_FRONTEND_REQUIREMENTS.md`
9. `09_BACKEND_WORKER_REQUIREMENTS.md`
10. `10_REPORTING_AND_EXPORTS.md`
11. `11_DOCKER_LOCAL_DEPLOYMENT.md`
12. `12_TESTING_AND_ACCEPTANCE.md`
13. `13_BUILD_PHASE_PLAN.md`
14. `14_CURSOR_IMPLEMENTATION_PROMPTS.md`
15. `15_SAMPLE_CONFIG_AND_RULES.md`

Then create the application with clean code, modular services, clear types/schemas, database migrations, tests, and Docker Compose support.

# Ajace TimeSheet AI Bot — Backend and Worker Requirements

## 1. Backend Responsibilities

FastAPI backend must handle:

- Upload APIs.
- Batch APIs.
- File inventory APIs.
- Validation APIs.
- Report APIs.
- Admin CRUD APIs.
- Database transactions.
- Job creation in Redis/Celery.
- Report downloads.

It should not perform long-running ZIP/OCR/LLM processing inside request-response lifecycle.

---

## 2. Worker Responsibilities

Celery worker must handle:

- Safe unzip.
- File scanning.
- File inventory creation.
- Duplicate detection.
- Parser routing.
- OCR.
- LLM normalization.
- Employee matching.
- Timesheet entry creation.
- Validation.
- Payroll calculation.
- Report generation.

---

## 3. Backend Project Structure

```text
backend/
  app/
    main.py
    core/
      config.py
      logging.py
      constants.py
    db/
      session.py
      models.py
      base.py
    schemas/
      batch.py
      file.py
      extraction.py
      timesheet.py
      validation.py
      payroll.py
      report.py
    api/
      deps.py
      v1/
        routes_batches.py
        routes_uploads.py
        routes_files.py
        routes_entries.py
        routes_validation.py
        routes_reports.py
        routes_admin.py
    services/
      storage_service.py
      zip_service.py
      file_inventory_service.py
      hash_service.py
      parser_router.py
      parsers/
        excel_parser.py
        csv_parser.py
        docx_parser.py
        pdf_text_parser.py
        pdf_ocr_parser.py
        image_ocr_parser.py
      ocr_service.py
      llm_service.py
      normalizer_service.py
      employee_match_service.py
      validation_service.py
      payroll_service.py
      report_service.py
      audit_service.py
    workers/
      celery_app.py
      tasks.py
    tests/
```

---

## 4. Celery Tasks

Create tasks:

```python
process_batch_task(batch_id: str)
process_file_task(file_id: str)
run_validation_task(batch_id: str)
generate_reports_task(batch_id: str)
```

MVP can process whole batch in one task. Later split file processing into parallel tasks.

---

## 5. Storage Paths

Use local mounted volume:

```text
/storage/uploads/{batch_id}/original.zip
/storage/extracted/{batch_id}/...
/storage/raw_extractions/{batch_id}/{file_id}.json
/storage/reports/{batch_id}/...
```

---

## 6. Safe ZIP Extraction Requirements

Implement:

- Path traversal prevention.
- Skip directories.
- Reject hidden system files unless allowed.
- Max file size config.
- Max total extraction size config.
- Preserve relative folder path.

Noise files:

```text
desktop.ini
.DS_Store
Thumbs.db
__MACOSX/*
```

---

## 7. Parser Router Requirements

Return a common extraction object:

```python
class RawExtractionResult(BaseModel):
    method: str
    raw_text: str | None
    raw_tables: list[dict]
    confidence: float
    warnings: list[str]
    metadata: dict
```

---

## 8. Employee Matching Requirements

Priority:

1. Employee ID exact match.
2. Email exact match.
3. Full name exact match.
4. Fuzzy name match.
5. Manual HR review.

Match result:

```python
class EmployeeMatchResult(BaseModel):
    employee_id: str | None
    detected_name: str | None
    match_method: str
    confidence: float
    requires_review: bool
```

Thresholds:

- >= 0.90 auto-match.
- 0.70 to 0.89 review suggested.
- < 0.70 manual review required.

---

## 9. Validation Service Requirements

Create a pure Python validation engine.

Input:

- Employee.
- Vendor.
- Payroll period.
- Timesheet submission.
- Timesheet entries.
- Holiday calendar.
- Employee rate.

Output:

- Updated entries with calculated regular/overtime hours.
- Validation error list.
- Payroll readiness status.

---

## 10. Error Handling

Every file-level exception must be caught.

Rules:

- Mark file failed.
- Save error message.
- Continue processing other files.
- Mark batch as `NEEDS_REVIEW`, not failed, unless system-level failure occurs.

---

## 11. Logging Requirements

Log each major stage:

- Upload received.
- ZIP extraction started/completed.
- File detected.
- Parser selected.
- OCR started/completed.
- LLM normalization started/completed.
- Employee matched.
- Validation completed.
- Report generated.

---

## 12. Audit Requirements

Create audit logs for:

- Manual employee assignment.
- Manual timesheet row edit.
- Validation error resolution.
- Approval status change.
- Payroll report generation.
- Employee status changed to inactive.

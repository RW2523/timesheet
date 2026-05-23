# Ajace TimeSheet AI Bot — System Architecture

## 1. Architecture Principle

This application must be parser-first, OCR-second, LLM-assisted, and rule-engine-final.

```text
Input Files
  → Deterministic Parser / OCR
  → LLM Cleanup only when needed
  → Standard JSON
  → Rule-Based Validation
  → HR Review
  → Payroll Report
```

Do not use the LLM as the final source of truth for payroll logic.

---

## 2. Recommended Local Stack

| Layer | Tool |
|---|---|
| Frontend | Next.js + TypeScript + Tailwind CSS |
| Backend API | Python FastAPI |
| Database | PostgreSQL |
| Queue | Redis + Celery |
| Workers | Python worker containers |
| File storage | Local Docker volume first; MinIO later |
| OCR | PaddleOCR + Docling + Tesseract fallback |
| PDF parsing | PyMuPDF + pdfplumber |
| Excel/CSV parsing | pandas + openpyxl |
| DOCX parsing | python-docx |
| LLM serving | TensorRT-LLM on DGX Spark |
| Primary LLM | Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 |
| Optional helper LLM | Qwen3-14B-FP4 |
| Optional review LLM | Qwen3-32B-FP4 |
| Reports | pandas + openpyxl |
| Deployment | Docker Compose |

---

## 3. High-Level Architecture

```text
┌─────────────────────┐
│  Next.js Frontend   │
└─────────┬───────────┘
          │ REST API
┌─────────▼───────────┐
│   FastAPI Backend   │
└────┬───────────┬────┘
     │           │
     │           ▼
     │     Redis Queue
     │           │
     ▼           ▼
PostgreSQL   Celery Worker
                 │
                 ▼
        File/OCR/LLM Pipeline
                 │
                 ▼
        Validation + Reports
                 │
                 ▼
        Local Storage / Reports
```

---

## 4. Runtime Services

### frontend

Responsible for:

- HR dashboard.
- ZIP upload.
- Batch tracking.
- File inventory review.
- Employee match review.
- Validation issue review.
- Payroll reports.
- Admin settings.

### backend

Responsible for:

- REST APIs.
- Authentication placeholder.
- Upload handling.
- Batch creation.
- Database reads/writes.
- Queue job creation.
- Report download API.

### worker

Responsible for:

- Safe ZIP extraction.
- Recursive file scanning.
- Hash duplicate detection.
- Parser routing.
- OCR.
- LLM cleanup.
- Employee matching.
- Validation.
- Report generation.

### postgres

Stores:

- Master data.
- Batch data.
- File inventory.
- Raw extraction.
- Normalized entries.
- Validation errors.
- Payroll results.
- Audit logs.

### redis

Used for:

- Celery broker.
- Job status.
- Worker coordination.
- Retry workflow.

### trt-llm

Can be external or containerized depending on DGX Spark setup.

Used for:

- JSON extraction from messy text.
- Filename/folder interpretation.
- Error explanation.

---

## 5. Module Boundaries

```text
app/
  api/
    routes_upload.py
    routes_batches.py
    routes_files.py
    routes_entries.py
    routes_validation.py
    routes_reports.py
    routes_admin.py
  core/
    config.py
    security.py
    logging.py
  db/
    session.py
    models.py
    migrations/
  services/
    storage_service.py
    batch_service.py
    file_inventory_service.py
    parser_router.py
    ocr_service.py
    llm_service.py
    employee_match_service.py
    validation_service.py
    payroll_service.py
    report_service.py
    notification_service.py
    audit_service.py
  workers/
    celery_app.py
    tasks.py
  schemas/
    batch.py
    file.py
    extraction.py
    timesheet.py
    validation.py
    report.py
```

---

## 6. Data Flow

### ZIP Upload Flow

```text
HR uploads ZIP
  → FastAPI saves ZIP to /storage/uploads
  → batch_uploads row created
  → Celery job queued
  → worker safely unzips
  → uploaded_files rows created
  → each file parsed/OCRed
  → raw_extractions saved
  → normalized entries saved
  → validation_errors saved
  → reports generated
  → dashboard updated
```

### Future Email Flow

```text
Email received at timesheets@ajace.com
  → email listener downloads attachment
  → source_type = EMAIL
  → same Common Processor
  → same validations/reports
```

---

## 7. Why Docker Compose Instead of Kubernetes

Use Docker Compose for MVP/local DGX Spark because:

- Easier to build.
- Easier to debug.
- Local-first requirement.
- No need for cluster orchestration yet.
- Services are limited and controlled.

Add Kubernetes later only if:

- Multiple machines are needed.
- Multiple teams deploy it.
- Horizontal scaling is required.
- Production cluster operations are needed.

---

## 8. Design Rule for Scalability

Keep the application modular even if using Docker Compose.

Do not write one large script. Build independent services/functions:

- `inventory_builder`
- `parser_router`
- `ocr_service`
- `llm_normalizer`
- `employee_matcher`
- `validation_engine`
- `report_generator`

This makes it easy to move to microservices later if needed.

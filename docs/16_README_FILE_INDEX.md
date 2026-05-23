# Ajace TimeSheet AI Bot — Documentation File Index

This folder contains Cursor-ready markdown files for building the full local Ajace TimeSheet AI Bot.

## Files

1. `00_START_HERE_CURSOR_MASTER_PROMPT.md`  
   Master prompt and non-negotiable system requirements.

2. `01_PRODUCT_REQUIREMENTS.md`  
   Complete PRD covering ZIP upload, future email, extraction, validation, payroll, and reporting.

3. `02_SYSTEM_ARCHITECTURE.md`  
   Full local Docker/FastAPI/Next.js/PostgreSQL/Redis/Celery/OCR/LLM architecture.

4. `03_DATABASE_SCHEMA.md`  
   PostgreSQL schema design with master, batch, file, extraction, timesheet, validation, payroll, report, notification, and audit tables.

5. `04_PROCESSING_PIPELINE.md`  
   End-to-end processing flow, safe unzip, file inventory, parser dispatch, extraction, normalization, validation, and reports.

6. `05_EXTRACTION_OCR_LLM_DESIGN.md`  
   Parser/OCR/LLM strategy, model recommendations, standard JSON schema, prompt template, and confidence rules.

7. `06_VALIDATION_RULES.md`  
   Complete rule engine specification for daily hours, weekly limits, overtime, holidays, leave, approval, late submission, missing timesheets, inactive employees, and salary calculation.

8. `07_API_SPEC.md`  
   REST API endpoints for uploads, batches, files, entries, validation, approvals, payroll, reports, and admin settings.

9. `08_FRONTEND_REQUIREMENTS.md`  
   Next.js dashboard/pages/components/UI requirements.

10. `09_BACKEND_WORKER_REQUIREMENTS.md`  
    FastAPI backend, Celery worker, parsers, services, storage, logging, and audit requirements.

11. `10_REPORTING_AND_EXPORTS.md`  
    Excel reports, sheets, columns, ADP export, and formatting requirements.

12. `11_DOCKER_LOCAL_DEPLOYMENT.md`  
    Docker Compose, Dockerfiles, environment variables, and local deployment plan.

13. `12_TESTING_AND_ACCEPTANCE.md`  
    Test cases and definition of done.

14. `13_BUILD_PHASE_PLAN.md`  
    Phase-by-phase implementation roadmap.

15. `14_CURSOR_IMPLEMENTATION_PROMPTS.md`  
    Copy-paste prompts for Cursor to implement each phase.

16. `15_SAMPLE_CONFIG_AND_RULES.md`  
    Sample vendor, payroll, employee, file ignore, and blocking rule configurations.

## How to Use in Cursor

1. Put this entire folder in your project root under `/docs`.
2. Open Cursor.
3. Ask Cursor to read `00_START_HERE_CURSOR_MASTER_PROMPT.md` first.
4. Then ask Cursor to implement one phase at a time using `14_CURSOR_IMPLEMENTATION_PROMPTS.md`.
5. Do not let Cursor skip phases.
6. After each phase, run and test before moving forward.

## Recommended First Cursor Command

```text
Read all files in /docs. Start with 00_START_HERE_CURSOR_MASTER_PROMPT.md. Build Phase 0 only: monorepo skeleton, Docker Compose, Next.js frontend, FastAPI backend, PostgreSQL, Redis, Celery worker, and health endpoints. Do not implement timesheet business logic yet.
```

# Ajace TimeSheet AI Bot — Database Schema

Use PostgreSQL as the main database.

The system must keep master data, raw extraction data, normalized timesheet entries, validation results, payroll runs, generated reports, and audit logs.

## 1. Schema Principles

- Store original files separately in file storage.
- Store file metadata and paths in PostgreSQL.
- Keep raw extraction output for audit/debugging.
- Keep normalized timesheet rows separately for validation/reporting.
- Never overwrite approved payroll data without audit trail.
- Use UUID primary keys.
- Use `jsonb` columns for flexible raw extraction and parser metadata.

---

## 2. Master Tables

### users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('HR', 'PAYROLL', 'ADMIN', 'MANAGER')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### employees

```sql
CREATE TABLE employees (
    id UUID PRIMARY KEY,
    employee_code TEXT UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE,
    vendor_id UUID,
    client_manager_id UUID,
    employee_type TEXT CHECK (employee_type IN ('AJACE_INTERNAL', 'CONTRACTOR', 'CLIENT_VENDOR')),
    is_active BOOLEAN DEFAULT TRUE,
    last_submission_month TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### vendors

```sql
CREATE TABLE vendors (
    id UUID PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    overtime_enabled BOOLEAN DEFAULT FALSE,
    regular_daily_limit NUMERIC DEFAULT 8,
    regular_weekly_limit NUMERIC DEFAULT 40,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### client_managers

```sql
CREATE TABLE client_managers (
    id UUID PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE,
    vendor_id UUID,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### employee_rates

```sql
CREATE TABLE employee_rates (
    id UUID PRIMARY KEY,
    employee_id UUID NOT NULL,
    regular_rate NUMERIC NOT NULL,
    overtime_rate NUMERIC,
    currency TEXT DEFAULT 'USD',
    effective_start_date DATE NOT NULL,
    effective_end_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### holiday_calendars

```sql
CREATE TABLE holiday_calendars (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    applies_to_employee_type TEXT,
    vendor_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### holiday_dates

```sql
CREATE TABLE holiday_dates (
    id UUID PRIMARY KEY,
    calendar_id UUID NOT NULL,
    holiday_date DATE NOT NULL,
    holiday_name TEXT NOT NULL,
    paid_hours NUMERIC DEFAULT 8,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### payroll_periods

```sql
CREATE TABLE payroll_periods (
    id UUID PRIMARY KEY,
    period_key TEXT UNIQUE NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    cutoff_date DATE NOT NULL,
    payroll_run_date DATE,
    status TEXT DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 3. Batch and File Tables

### batch_uploads

```sql
CREATE TABLE batch_uploads (
    id UUID PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('ZIP_UPLOAD', 'EMAIL')),
    source_name TEXT NOT NULL,
    payroll_period_id UUID,
    uploaded_by UUID,
    original_file_path TEXT,
    status TEXT NOT NULL DEFAULT 'UPLOADED',
    total_files INTEGER DEFAULT 0,
    ignored_files INTEGER DEFAULT 0,
    duplicate_files INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    review_required_files INTEGER DEFAULT 0,
    payroll_ready_count INTEGER DEFAULT 0,
    summary_json JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### uploaded_files

```sql
CREATE TABLE uploaded_files (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL,
    folder_path TEXT,
    file_name TEXT NOT NULL,
    file_ext TEXT,
    file_size_bytes BIGINT,
    file_hash TEXT,
    stored_file_path TEXT,
    detected_employee_name TEXT,
    detected_vendor_name TEXT,
    detected_period_text TEXT,
    matched_employee_id UUID,
    match_confidence NUMERIC,
    match_status TEXT DEFAULT 'NOT_MATCHED',
    parser_name TEXT,
    ocr_required BOOLEAN DEFAULT FALSE,
    is_duplicate BOOLEAN DEFAULT FALSE,
    duplicate_of_file_id UUID,
    is_noise_file BOOLEAN DEFAULT FALSE,
    is_timesheet_candidate BOOLEAN DEFAULT TRUE,
    processing_status TEXT DEFAULT 'DETECTED',
    alerts_json JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### file_processing_logs

```sql
CREATE TABLE file_processing_logs (
    id UUID PRIMARY KEY,
    file_id UUID NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 4. Extraction Tables

### raw_extractions

```sql
CREATE TABLE raw_extractions (
    id UUID PRIMARY KEY,
    file_id UUID NOT NULL,
    extraction_method TEXT NOT NULL,
    raw_text TEXT,
    raw_tables JSONB,
    llm_json JSONB,
    confidence NUMERIC,
    extraction_warnings JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### employee_file_matches

```sql
CREATE TABLE employee_file_matches (
    id UUID PRIMARY KEY,
    file_id UUID NOT NULL,
    detected_name TEXT,
    matched_employee_id UUID,
    match_method TEXT,
    match_confidence NUMERIC,
    review_status TEXT DEFAULT 'AUTO',
    reviewed_by UUID,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 5. Timesheet Tables

### timesheet_submissions

```sql
CREATE TABLE timesheet_submissions (
    id UUID PRIMARY KEY,
    batch_id UUID,
    file_id UUID,
    employee_id UUID,
    payroll_period_id UUID,
    vendor_id UUID,
    source_type TEXT NOT NULL,
    submission_date TIMESTAMP,
    timesheet_start_date DATE,
    timesheet_end_date DATE,
    approval_status TEXT DEFAULT 'PENDING',
    approved_by_name TEXT,
    approved_by_email TEXT,
    approved_at TIMESTAMP,
    validation_status TEXT DEFAULT 'PENDING',
    payroll_status TEXT DEFAULT 'NOT_READY',
    is_late BOOLEAN DEFAULT FALSE,
    payable_period_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### timesheet_entries

```sql
CREATE TABLE timesheet_entries (
    id UUID PRIMARY KEY,
    submission_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    work_date DATE NOT NULL,
    day_of_week TEXT,
    in_time TIME,
    out_time TIME,
    break_minutes INTEGER DEFAULT 0,
    entered_hours NUMERIC,
    calculated_hours NUMERIC,
    regular_hours NUMERIC DEFAULT 0,
    overtime_hours NUMERIC DEFAULT 0,
    entry_type TEXT DEFAULT 'WORK',
    leave_type TEXT,
    is_holiday BOOLEAN DEFAULT FALSE,
    holiday_name TEXT,
    source_file_id UUID,
    row_source JSONB,
    validation_status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 6. Validation and Approval Tables

### validation_errors

```sql
CREATE TABLE validation_errors (
    id UUID PRIMARY KEY,
    batch_id UUID,
    file_id UUID,
    submission_id UUID,
    entry_id UUID,
    employee_id UUID,
    rule_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'BLOCKER')),
    message TEXT NOT NULL,
    expected_value TEXT,
    actual_value TEXT,
    action_required TEXT,
    assigned_to_role TEXT,
    status TEXT DEFAULT 'OPEN',
    resolved_by UUID,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### approval_records

```sql
CREATE TABLE approval_records (
    id UUID PRIMARY KEY,
    submission_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    approver_name TEXT,
    approver_email TEXT,
    approval_status TEXT NOT NULL CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    approval_source TEXT,
    approval_date TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 7. Payroll Tables

### payroll_runs

```sql
CREATE TABLE payroll_runs (
    id UUID PRIMARY KEY,
    payroll_period_id UUID NOT NULL,
    run_by UUID,
    run_status TEXT DEFAULT 'DRAFT',
    total_employees INTEGER DEFAULT 0,
    payroll_ready_employees INTEGER DEFAULT 0,
    blocked_employees INTEGER DEFAULT 0,
    total_regular_hours NUMERIC DEFAULT 0,
    total_overtime_hours NUMERIC DEFAULT 0,
    total_regular_pay NUMERIC DEFAULT 0,
    total_overtime_pay NUMERIC DEFAULT 0,
    total_pay NUMERIC DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### payroll_results

```sql
CREATE TABLE payroll_results (
    id UUID PRIMARY KEY,
    payroll_run_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    vendor_id UUID,
    regular_hours NUMERIC DEFAULT 0,
    overtime_hours NUMERIC DEFAULT 0,
    leave_days NUMERIC DEFAULT 0,
    holiday_hours NUMERIC DEFAULT 0,
    regular_rate NUMERIC,
    overtime_rate NUMERIC,
    regular_pay NUMERIC DEFAULT 0,
    overtime_pay NUMERIC DEFAULT 0,
    total_pay NUMERIC DEFAULT 0,
    payroll_status TEXT DEFAULT 'READY',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### generated_reports

```sql
CREATE TABLE generated_reports (
    id UUID PRIMARY KEY,
    batch_id UUID,
    payroll_run_id UUID,
    report_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    generated_by UUID,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 8. Notification and Audit Tables

### notification_logs

```sql
CREATE TABLE notification_logs (
    id UUID PRIMARY KEY,
    employee_id UUID,
    recipient_email TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    status TEXT DEFAULT 'PENDING',
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### audit_logs

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    actor_user_id UUID,
    entity_type TEXT NOT NULL,
    entity_id UUID,
    action TEXT NOT NULL,
    before_json JSONB,
    after_json JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 9. Useful Indexes

```sql
CREATE INDEX idx_uploaded_files_batch_id ON uploaded_files(batch_id);
CREATE INDEX idx_uploaded_files_hash ON uploaded_files(file_hash);
CREATE INDEX idx_timesheet_entries_employee_date ON timesheet_entries(employee_id, work_date);
CREATE INDEX idx_validation_errors_status ON validation_errors(status);
CREATE INDEX idx_timesheet_submissions_employee_period ON timesheet_submissions(employee_id, payroll_period_id);
CREATE INDEX idx_payroll_results_run ON payroll_results(payroll_run_id);
```

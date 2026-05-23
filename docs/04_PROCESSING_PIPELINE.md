# Ajace TimeSheet AI Bot — Processing Pipeline

## 1. Main Pipeline

```text
Input Source: ZIP_UPLOAD or EMAIL
        ↓
Create Batch Record
        ↓
Store Original Input
        ↓
Build File Inventory
        ↓
Detect File Type + Hash + Metadata
        ↓
Ignore Noise / Detect Duplicates
        ↓
Parser Router
        ↓
Direct Parser or OCR/Layout Parser
        ↓
Raw Extraction Stored
        ↓
LLM Cleanup to Standard JSON
        ↓
Employee Matching
        ↓
Normalize Timesheet Entries
        ↓
Merge Employee Month Records
        ↓
Validation Engine
        ↓
HR Review / Alerts
        ↓
Payroll Calculation
        ↓
Excel / ADP Export
```

---

## 2. Main Function Contract

Create a main function like this:

```python
def process_timesheet_batch(
    source_type: str,
    source_path: str,
    payroll_period_id: str,
    uploaded_by: str | None = None,
) -> dict:
    """
    Process a ZIP upload or future email source end to end.
    Returns batch summary and generated report paths.
    """
```

---

## 3. ZIP Upload Pipeline

### Step 1: Save Upload

- Save ZIP to `/storage/uploads/{batch_id}/original.zip`.
- Create `batch_uploads` record.
- Queue Celery job.

### Step 2: Safe Unzip

Rules:

- Prevent ZIP slip path traversal.
- Reject executable files.
- Limit max extracted file size if configured.
- Extract to `/storage/extracted/{batch_id}`.

### Step 3: Recursive Scan

Scan all files in all subfolders.

For each file:

- Capture relative folder path.
- Capture file name.
- Capture extension.
- Capture file size.
- Compute SHA256 hash.
- Detect noise files.
- Detect duplicates.
- Create `uploaded_files` record.

### Step 4: Folder/File Intelligence

Infer metadata from:

- Folder name.
- Subfolder name.
- File name.
- Date patterns.
- Vendor names.
- Employee names.

Examples:

```text
NPO/John_Smith_March_2026.xlsx
→ vendor=NPO, employee=John Smith, period=March 2026
```

```text
TangiralaG_20260403.pdf
→ possible employee=Tangirala G, partial week ending 2026-04-03
```

### Step 5: Parser Dispatch

```python
if file_ext in [".xlsx", ".xls"]:
    parse_excel(file)
elif file_ext == ".csv":
    parse_csv(file)
elif file_ext == ".docx":
    parse_docx(file)
elif file_ext == ".pdf":
    if has_text_layer(file):
        parse_pdf_text(file)
    else:
        parse_pdf_ocr(file)
elif file_ext in [".png", ".jpg", ".jpeg"]:
    parse_image_ocr(file)
else:
    mark_unsupported(file)
```

### Step 6: Raw Extraction Storage

Store:

- Raw text.
- Raw tables.
- OCR text.
- Layout metadata.
- Parser confidence.
- Warnings.

### Step 7: Standard JSON

Use deterministic mapping first. Use LLM only when needed.

### Step 8: Employee Matching

Match to `employees` table.

### Step 9: Normalize Rows

Create `timesheet_entries` rows.

### Step 10: Validate

Run all validation rules.

### Step 11: Generate Reports

Create Excel files and update batch status.

---

## 4. Email Pipeline for Future

Future email ingestion should use same common processor.

```text
Email Listener
  → Download Attachments
  → Create Batch or Submission
  → Store Files
  → Common Processor
```

Email metadata to capture:

- Sender.
- Subject.
- Received timestamp.
- Message ID.
- Attachment names.
- Body text.

---

## 5. Status Updates

Update status after each stage.

```text
UPLOADED → UNZIPPING → SCANNING → PROCESSING → VALIDATING → REPORT_READY
```

For each file:

```text
DETECTED → PARSING → EXTRACTED → VALIDATED → PAYROLL_READY
```

Or error statuses:

```text
IGNORED
DUPLICATE
OCR_REQUIRED
UNSUPPORTED
FAILED
MATCH_REVIEW_REQUIRED
VALIDATION_FAILED
PAYROLL_BLOCKED
```

---

## 6. Alert Generation

Generate alerts for:

- OCR required.
- Unsupported file.
- Duplicate file.
- Non-timesheet document.
- Employee match required.
- Payroll period mismatch.
- Partial period file.
- Overlapping dates.
- Missing approval.
- Hours mismatch.
- Missing holiday entry.
- Overtime not allowed.
- Late submission.

---

## 7. Batch Completion Rules

Batch can be completed even if some files failed.

Final batch status rules:

| Condition | Batch Status |
|---|---|
| All files processed and no blockers | COMPLETED |
| Some files need HR review | NEEDS_REVIEW |
| Reports generated but payroll blocked for some | REPORT_READY_WITH_EXCEPTIONS |
| System-level failure | FAILED |

---

## 8. Pseudocode

```python
def process_timesheet_batch(source_type, source_path, payroll_period_id, uploaded_by=None):
    batch = create_batch(source_type, source_path, payroll_period_id, uploaded_by)

    try:
        if source_type == "ZIP_UPLOAD":
            extracted_root = safe_unzip(source_path, batch.id)
            files = scan_files(extracted_root)
        else:
            files = load_email_attachments(source_path)

        inventory = build_file_inventory(batch.id, files)

        for file_record in inventory:
            try:
                if is_noise_file(file_record):
                    mark_ignored(file_record)
                    continue

                if is_duplicate(file_record):
                    mark_duplicate(file_record)
                    continue

                extraction = parse_or_ocr_file(file_record)
                save_raw_extraction(file_record.id, extraction)

                normalized = normalize_to_timesheet_json(file_record, extraction)
                match = match_employee(normalized, file_record)

                if match.requires_review:
                    create_alert(file_record, "EMPLOYEE_MATCH_REQUIRED")

                submission = create_submission(file_record, normalized, match)
                entries = create_entries(submission, normalized)

                validation_result = validate_submission(submission, entries)
                save_validation_errors(validation_result)

            except Exception as e:
                mark_file_failed(file_record, str(e))

        merge_employee_month_records(batch.id)
        detect_missing_timesheets(batch.id, payroll_period_id)
        report_paths = generate_reports(batch.id)
        update_batch_summary(batch.id)

        return get_batch_summary(batch.id, report_paths)

    except Exception as e:
        mark_batch_failed(batch.id, str(e))
        raise
```

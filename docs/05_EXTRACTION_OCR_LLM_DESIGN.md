# Ajace TimeSheet AI Bot — Extraction, OCR, and LLM Design

## 1. Extraction Philosophy

Use the cheapest reliable method first.

```text
1. Direct structured parser
2. PDF text/table parser
3. OCR/layout extraction
4. LLM cleanup into strict JSON
5. Manual review if confidence is low
```

Do not use OCR or LLM for every file unnecessarily.

---

## 2. Parser Router

| File Type | Primary Tool | Fallback |
|---|---|---|
| XLSX/XLS | pandas + openpyxl | LLM cleanup if columns unclear |
| CSV | pandas | LLM cleanup if headers unclear |
| DOCX | python-docx | OCR if embedded image only |
| Text PDF | PyMuPDF + pdfplumber | Docling |
| Scanned PDF | Docling + PaddleOCR | Tesseract |
| PNG/JPG/JPEG | PaddleOCR | Tesseract |
| Unknown | Mark unsupported | HR review |

---

## 3. OCR Strategy

### Primary OCR

Use:

```text
PaddleOCR
Docling
```

Use PaddleOCR for image text extraction and Docling for document structure/layout/table detection.

### Fallback OCR

Use:

```text
Tesseract
```

Only when primary OCR fails or is unavailable.

### OCR Required Detection

For PDFs:

- Try text extraction using PyMuPDF.
- If extracted text length is low, mark `OCR_REQUIRED`.
- If pages are image-heavy, mark `OCR_REQUIRED`.

Example rule:

```python
if pdf_text_chars < 100 or average_text_chars_per_page < 30:
    ocr_required = True
```

---

## 4. LLM Model Selection

Use TensorRT-LLM on DGX Spark.

### Primary Model

```text
nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4
```

Use for:

- Messy OCR cleanup.
- Extracting structured timesheet rows from noisy text.
- Understanding uncommon templates.
- Explaining validation errors.

### Fast Helper Model

```text
nvidia/Qwen3-14B-FP4
```

Use for:

- Filename cleanup.
- Vendor detection.
- Simple classification.
- Quick JSON extraction.

### Review Model

```text
nvidia/Qwen3-32B-FP4
```

Use only when:

- OCR confidence is low.
- Employee matching is uncertain.
- Date ranges overlap.
- Extraction result conflicts with validation.

---

## 5. LLM Responsibilities

LLM can do:

- Convert raw OCR text into JSON.
- Identify likely employee name from messy file/folder names.
- Identify timesheet period from file/folder/content.
- Map unusual column headers to standard fields.
- Produce human-readable issue explanation.

LLM must not do:

- Final salary calculation.
- Final overtime decision.
- Final approval decision.
- Final payroll export decision.

---

## 6. Standard Extraction Schema

All extractors must output this structure:

```json
{
  "employee": {
    "name": null,
    "employee_id": null,
    "email": null
  },
  "vendor": null,
  "client": null,
  "timesheet_period": {
    "start_date": null,
    "end_date": null,
    "period_text": null
  },
  "entries": [
    {
      "date": null,
      "day": null,
      "in_time": null,
      "out_time": null,
      "break_minutes": 0,
      "entered_hours": null,
      "entry_type": "work",
      "leave_type": null,
      "holiday_name": null,
      "notes": null
    }
  ],
  "approval": {
    "status": "unknown",
    "approver_name": null,
    "approver_email": null,
    "approval_date": null
  },
  "confidence": 0.0,
  "warnings": []
}
```

---

## 7. LLM Prompt Template

Use this prompt in the LLM service when raw extraction is messy.

```text
You are extracting timesheet data for payroll validation.
Return only valid JSON matching the required schema.
Do not calculate salary.
Do not invent missing values.
Use null when a field is missing.
Preserve every date row you can identify.
If a value is uncertain, include a warning.

Required fields:
- employee.name
- employee.employee_id
- employee.email
- vendor
- client
- timesheet_period.start_date
- timesheet_period.end_date
- entries[].date
- entries[].in_time
- entries[].out_time
- entries[].break_minutes
- entries[].entered_hours
- entries[].entry_type
- entries[].leave_type
- entries[].holiday_name
- approval.status
- approval.approver_name
- approval.approval_date
- confidence
- warnings

Raw file metadata:
{file_metadata}

Raw extracted text/tables:
{raw_content}
```

---

## 8. Confidence Rules

Set confidence levels:

| Condition | Confidence |
|---|---:|
| Structured Excel with clear headers | 0.95 |
| Text PDF with clear table | 0.85 |
| OCR with clear text | 0.75 |
| OCR with messy rows | 0.55 |
| Missing employee or dates | 0.40 |
| Unreadable file | 0.00 |

If confidence < 0.70, require HR review.

---

## 9. File Classification

Classify each file as:

```text
TIMESHEET
POSSIBLE_TIMESHEET
NON_TIMESHEET_DOCUMENT
UNSUPPORTED
NOISE_FILE
```

Non-timesheet examples:

- Reimbursement file.
- Contract file.
- Invoice not related to hours.
- Empty file.

---

## 10. Extraction Error Handling

Do not crash the batch.

If extraction fails:

- Mark file as `FAILED`.
- Save error message.
- Create validation alert.
- Continue with next file.

If OCR fails:

- Mark `OCR_FAILED`.
- Require manual review.

If LLM JSON is invalid:

- Retry once with stricter prompt.
- If still invalid, save raw output and require manual review.

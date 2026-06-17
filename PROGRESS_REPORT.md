# Timesheet AI — Progress Report

_Last updated: 2026-06-17_

## Goal
Turn unstructured timesheets (PDF, Excel, CSV, DOCX, images — many vendor formats)
into clean structured data, show each employee's month in a calendar with
hours-per-day, and surface what is missing. Employee matching is treated as
optional metadata, never a gate on extraction.

---

## What works now

### Extraction (unstructured → structured)
- **Schema-enforced LLM output.** The extractor constrains the model to a JSON
  schema (Ollama `format` / OpenAI+TRT `response_format`), validates with
  Pydantic, and retries once on a bad response instead of silently dropping the
  document. Risky "verification" pass is off by default.
- **Table preservation.** Excel/CSV keep empty cells positionally (no more column
  shifting); CSV sniffs the delimiter and reports dropped rows; Docling NaN fixed.
- **OCR + VLM fusion** for image-based docs: OCR extracts accurate characters +
  geometry, a vision model rebuilds table layout grounded on that OCR text, and
  the result is parsed into real tables. Available in the lab and (opt-in) the
  pipeline. Image sent to the VLM is downscaled for reliability.
- **3-way engine race** for images/scanned PDFs: flat OCR, OCR+VLM fusion, and
  VLM-only are all run and the best-scoring result is kept.
- **Shared date handling** with configurable locale (`DATE_DAYFIRST`).

### Matching is now optional
- Every candidate file produces a full structured timesheet whether or not it
  matches an employee in the roster. The extracted name is stored for display.
- `EMPLOYEE_NOT_MATCHED` is a non-blocking warning, not a blocker.

### Calendar preview (simple, interactive)
- Month grid with **hours per day** in each cell, color-coded by type
  (work / overtime / leave / holiday / absent), click a day for in/out/break.
- **Shows what is missing**: weekdays inside the timesheet period with no hours
  are flagged ("missing", with a count); files that produced no timesheet at all
  are listed separately.
- Lives in the **batch view** (Calendar tab) and the **Pipeline Test Lab**.

### Payroll correctness (earlier work)
- Weekly-overtime reclassification, period-correct pay rates, second-shift
  retention, CSV/Excel formula-injection neutralized.

---

## Latest verification run (10-file sample, batch `2b821fdb`)

| Outcome | Count | Notes |
|---|---|---|
| Full structured timesheet | **7 / 10** | 19–30 day entries each |
| Not extracted | 3 / 10 | image-only `.docx`, low-quality `.png` + `.jpg` |
| End-to-end incl. employee match | 2 | only 2 employees exist in the roster |

Before the matching-decouple work only **2/10** files yielded data; now **7/10** do.
The 3 misses are genuine extraction-quality cases, not the matching gate.

---

## Known issues / next steps

1. **Image-only `.docx`** isn't handled by the multi-engine yet (needs embedded-image
   extraction first). — _highest-value fix_
2. **Low-quality `.png` / `.jpg`** OCR yields little or garbage (e.g. wrong year,
   invalid dates). Needs image pre-processing (deskew/upscale) or better OCR.
3. **Extraction-quality anomalies** the calendar already exposes: one file showed
   ~9800h for a month (misread column); a couple of sheets didn't extract the
   employee name. Worth a per-row sanity check (cap implausible daily hours).
4. **Roster**: only 4 employees seeded. Matching is optional so this no longer
   blocks data, but seeding the roster would enable employee-level linking and a
   true "missing employee" report.

---

## How to use
- App UI: **http://localhost:3000**
- A processed batch → **Calendar** tab shows each employee's month + what's missing.
- **Pipeline Test Lab**: upload one file, run parsers (incl. **OCR + VLM Fusion**),
  send to the LLM, and view the **Calendar** sub-tab of the result.

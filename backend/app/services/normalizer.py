"""
Normalizer service — Phase 4.
5-pass extraction pipeline:
  Pass 1 + 2: Deterministic table → row mapping
  Pass 3:     Text heuristics (date/time pattern matching)
  Pass 4:     LLM extraction (Ollama — non-optional when LLM_ENABLED=true)
  Pass 5:     LLM verification and period filter

Key invariants (payroll safety):
- A file is only set to NORMALIZED if it has ≥1 valid entry with a date AND at least
  NORMALIZATION_MIN_HOURS_RATIO fraction of entries have hours or in/out times.
  Otherwise status = NEEDS_REVIEW (never silently NORMALIZED).
- Out-of-period entries are kept in raw extraction but flagged; they are removed from
  the entries list that drives payroll — a warning OUT_OF_PERIOD_ENTRY is stored in
  extraction_warnings so HR can see them in reports.
- LLM must not create entries for missing days. Only FILE_EXTRACTED source is payroll-valid.
"""
import re
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session

from app.db.models import RawExtraction, UploadedFile, FileProcessingLog, gen_uuid
from app.services.llm_service import LLMService
from app.core.config import settings

logger = logging.getLogger(__name__)

DATE_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}",
    r"\d{1,2}/\d{1,2}/\d{4}",
    r"\d{1,2}-\d{1,2}-\d{4}",
    r"\d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{4}",
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
    # DD/MM/YYYY (European) — parsed with dayfirst=True where ambiguous
    r"\d{2}/\d{2}/\d{4}",
]

HEADER_KEYWORDS = [
    "date", "day", "in", "out", "hours", "regular", "overtime",
    "leave", "holiday", "total", "time", "clock", "worked", "sick", "vacation",
    "billable", "daily", "non-billable", "hrs", "start", "end", "punch",
]

TIME_KEYWORDS = ["in", "out", "start", "end", "clock in", "clock out", "time in", "time out", "punch in", "punch out"]
HOURS_KEYWORDS = ["regular", "total hrs", "total hours", "worked", "hours", "overtime", "billable"]
BREAK_KEYWORDS = ["break", "lunch", "minus", "deduct", "unpaid"]

# Base non-name tokens (period/label noise) — company tokens come from settings
_BASE_GARBAGE_WORDS = {
    # Time / period noise
    "week", "start", "end", "ending", "starting", "record", "time", "sheet",
    "monthly", "weekly", "daily", "timesheet", "bi", "bimonthly", "semi",
    # Column / field labels
    "in", "out", "hrs", "hours", "regular", "total", "billable",
    "classification", "overtime", "date", "period", "payroll",
    # Month abbreviations (May omitted — too common as a word)
    "jan", "feb", "mar", "apr", "jun", "jul", "aug",
    "sep", "oct", "nov", "dec",
    # Full month names
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    # File type suffixes (in case extension leaked into name)
    "pdf", "csv", "xlsx", "docx", "xls", "doc",
    # Generic doc titles
    "ts",
}

def _get_garbage_words() -> set:
    """Build the full garbage word set (base + company stopwords from config)."""
    return _BASE_GARBAGE_WORDS | settings.company_stopwords


class NormalizerService:
    def __init__(self, db: Session):
        self.db = db
        self.llm = LLMService()

    def normalize(self, raw_ext: RawExtraction) -> Optional[Dict[str, Any]]:
        """Run all extraction passes. Best result is stored."""
        candidates: List[Dict[str, Any]] = []

        file_record = self.db.query(UploadedFile).filter(UploadedFile.id == raw_ext.file_id).first()
        file_path = file_record.stored_file_path if file_record else None
        file_name = file_record.file_name if file_record else None

        # Pass 1 + 2: Table-based extraction
        if raw_ext.raw_tables:
            table_result = self._normalize_tables(raw_ext.raw_tables)
            if table_result and table_result.get("entries"):
                candidates.append(table_result)

        # Pass 3: Text heuristics
        if raw_ext.raw_text and not candidates:
            text_result = self._normalize_text(raw_ext.raw_text)
            if text_result and text_result.get("entries"):
                candidates.append(text_result)

        # Pass 4: LLM extraction — always run if:
        #   a) No good result so far, OR
        #   b) Table result has fewer than LLM_TRIGGER_MIN_ENTRIES (suspect), OR
        #   c) Employee name not found in any candidate
        best_so_far = self._best_candidate(candidates)
        need_llm = (
            not best_so_far
            or len(best_so_far.get("entries", [])) < settings.LLM_TRIGGER_MIN_ENTRIES
            or not best_so_far.get("employee_name")
        )

        if need_llm and self.llm.is_enabled() and raw_ext.raw_text:
            try:
                llm_result = self.llm.extract_timesheet_json(
                    raw_ext.raw_text,
                    file_metadata={"file_id": str(raw_ext.file_id)},
                    verify=True,
                )
                if llm_result and llm_result.get("entries"):
                    if llm_result.get("employee_name"):
                        llm_result["employee_name"] = self._clean_employee_name(llm_result["employee_name"])
                    if best_so_far and len(best_so_far.get("entries", [])) >= len(llm_result.get("entries", [])):
                        if not best_so_far.get("employee_name") and llm_result.get("employee_name"):
                            best_so_far["employee_name"] = llm_result["employee_name"]
                        candidates.append(best_so_far)
                    else:
                        candidates.append(llm_result)
            except Exception as e:
                logger.warning(f"LLM extraction failed for {raw_ext.file_id}: {e}")

        # Pick best result
        result = self._best_candidate(candidates)

        # Post-process: clean outlier dates, fix times
        if result and result.get("entries"):
            result = self._clean_entries(result)
            result = self._fix_times(result)

        # Employee name resolution (priority order):
        # 1. Filename (HR named the file — most reliable)
        # 2. Validate/clean LLM name; clear if it looks like an address
        # 3. Fallback: scan raw text for signature/label patterns
        if result:
            filename_name = self._find_employee_name_from_filename(file_name) if file_name else None

            if filename_name:
                result["employee_name"] = self._clean_employee_name(filename_name)
                logger.info(f"Employee name from filename: {result['employee_name']}")
            else:
                candidate = self._clean_employee_name(result.get("employee_name"))
                result["employee_name"] = candidate

                if candidate:
                    addr_kws = ("court", "ave", "blvd", "street", "drive", "road", "lane",
                                "place", "circle", "way", "boulevard", "parkway")
                    addr_in_raw = any(kw in (raw_ext.raw_text or "").lower() for kw in addr_kws)
                    if addr_in_raw and candidate.lower() in (raw_ext.raw_text or "").lower():
                        pattern = re.compile(
                            r"\d+\w*\s+" + re.escape(candidate)
                            + r"\s+(?:court|ave|blvd|street|drive|road|lane|place|circle|way|boulevard|parkway)",
                            re.IGNORECASE,
                        )
                        if pattern.search(raw_ext.raw_text or ""):
                            logger.warning(f"Employee name '{candidate}' looks like address — clearing")
                            result["employee_name"] = None
                            candidate = None

                if not result.get("employee_name"):
                    text_name = self._clean_employee_name(
                        self._find_employee_name_from_text(raw_ext.raw_text or "")
                    )
                    if text_name:
                        result["employee_name"] = text_name

        # Pass 5: Apply batch period filter
        # Out-of-period entries are NOT silently dropped — they are moved to
        # a separate list in extraction_warnings as OUT_OF_PERIOD_ENTRY alerts.
        out_of_period_entries: List[Dict] = []
        if result and result.get("entries"):
            batch_record = None
            try:
                file_rec = self.db.query(UploadedFile).filter(UploadedFile.id == raw_ext.file_id).first()
                if file_rec:
                    from app.db.models import BatchUpload
                    batch_record = self.db.query(BatchUpload).filter(BatchUpload.id == file_rec.batch_id).first()
            except Exception:
                pass

            if batch_record and (batch_record.filter_period_start or batch_record.filter_period_end):
                ps = batch_record.filter_period_start
                pe = batch_record.filter_period_end
                before = len(result["entries"])
                in_period = []
                for entry in result["entries"]:
                    d = entry.get("date") or ""
                    if d:
                        if (ps and d < ps) or (pe and d > pe):
                            out_of_period_entries.append({
                                "date": d,
                                "rule_code": "OUT_OF_PERIOD_ENTRY",
                                "message": f"Entry {d} outside selected period {ps}→{pe}",
                            })
                            continue
                    in_period.append(entry)

                if out_of_period_entries:
                    logger.info(
                        f"Period filter {ps}→{pe}: moved {len(out_of_period_entries)} "
                        f"out-of-period entries to warnings (kept {len(in_period)})"
                    )
                result["entries"] = in_period
                if in_period:
                    result["period_start"] = in_period[0]["date"]
                    result["period_end"] = in_period[-1]["date"]

        # Persist result
        # Determine status using strict rules:
        #  - NORMALIZED: has valid entries AND sufficient proportion have hours or in/out
        #  - NEEDS_REVIEW: no valid entries, or low-confidence extraction
        if result:
            raw_ext.llm_json = result
            confidence = self._score_result(result)
            raw_ext.confidence = confidence

            # Add out-of-period warnings to extraction_warnings
            if out_of_period_entries:
                existing_warns = list(raw_ext.extraction_warnings or [])
                existing_warns.extend([e["message"] for e in out_of_period_entries])
                raw_ext.extraction_warnings = existing_warns

            file = self.db.query(UploadedFile).filter(UploadedFile.id == raw_ext.file_id).first()
            if file:
                status = self._determine_file_status(result, confidence)
                file.processing_status = status
                file.updated_at = datetime.utcnow()
                if status == "NEEDS_REVIEW":
                    self._log(str(raw_ext.file_id), "NORMALIZE", "LOW_CONFIDENCE",
                              f"Status=NEEDS_REVIEW, confidence={confidence:.2f}")
            self.db.commit()
        else:
            file = self.db.query(UploadedFile).filter(UploadedFile.id == raw_ext.file_id).first()
            if file:
                file.processing_status = "EXTRACTION_FAILED"
                file.updated_at = datetime.utcnow()
            raw_ext.llm_json = None
            self._log(str(raw_ext.file_id), "NORMALIZE", "FAILED",
                      "No extractable timesheet data after all passes")
            self.db.commit()

        return result

    @staticmethod
    def _determine_file_status(result: Dict[str, Any], confidence: float) -> str:
        """Decide whether extraction is NORMALIZED, NEEDS_REVIEW, or EXTRACTION_FAILED.

        Rules:
        - Must have at least NORMALIZATION_MIN_ENTRIES valid entries.
        - At least NORMALIZATION_MIN_DATED_RATIO fraction must have a parseable date.
        - At least NORMALIZATION_MIN_HOURS_RATIO fraction must have hours or in/out times.
        - Confidence must be >= OCR_CONFIDENCE_THRESHOLD.
        """
        entries = result.get("entries") or []
        min_entries = settings.NORMALIZATION_MIN_ENTRIES
        dated_ratio = settings.NORMALIZATION_MIN_DATED_RATIO
        hours_ratio = settings.NORMALIZATION_MIN_HOURS_RATIO
        conf_threshold = settings.OCR_CONFIDENCE_THRESHOLD

        if not entries or len(entries) < min_entries:
            return "NEEDS_REVIEW"

        dated = sum(1 for e in entries if e.get("date"))
        with_hours = sum(
            1 for e in entries
            if (e.get("hours") is not None and float(e.get("hours") or 0) > 0)
            or (e.get("in_time") and e.get("out_time"))
        )

        if (dated / len(entries)) < dated_ratio:
            return "NEEDS_REVIEW"
        if (with_hours / len(entries)) < hours_ratio:
            return "NEEDS_REVIEW"
        if confidence < conf_threshold:
            return "NEEDS_REVIEW"

        return "NORMALIZED"

    # ── Table normalization ───────────────────────────────────────────────────

    def _normalize_tables(self, raw_tables: List[Dict]) -> Optional[Dict[str, Any]]:
        """Map table rows to standardised entries using header detection.

        Multiple sheets that span ≤65 days are merged into one result.
        """
        sheet_results: List[Dict] = []

        for table in raw_tables:
            rows = table.get("rows", [])
            if len(rows) < 2:
                continue

            header_idx, header_row = self._find_header_row(rows)
            if header_idx is None:
                continue

            columns = [str(c or "").lower().replace("\n", " ").strip() for c in header_row]
            entries = []

            for row in rows[header_idx + 1:]:
                if len(row) < 2:
                    continue
                if all(not str(c or "").strip() for c in row):
                    continue
                entry = self._map_row(columns, row)
                if entry and entry.get("date"):
                    entries.append(entry)

            if entries:
                employee_name = self._find_employee_name(rows[:header_idx])
                period_start, period_end = self._extract_period_from_header(rows[:header_idx])
                sheet_results.append({
                    "employee_name": employee_name,
                    "period_start": entries[0]["date"] if entries else period_start,
                    "period_end": entries[-1]["date"] if entries else period_end,
                    "entries": entries,
                    "sheet": table.get("sheet", ""),
                })

        if not sheet_results:
            return None

        timesheet_sheets = [s for s in sheet_results if len(s["entries"]) > 0]

        if len(timesheet_sheets) > 1:
            all_entries: List[Dict] = []
            employee_name = None
            seen_dates: set = set()
            for sheet in timesheet_sheets:
                if not employee_name and sheet.get("employee_name"):
                    employee_name = sheet["employee_name"]
                for e in sheet["entries"]:
                    d = e.get("date")
                    if d and d not in seen_dates:
                        all_entries.append(e)
                        seen_dates.add(d)

            from dateutil import parser as dp_local
            def _date_key(e):
                try:
                    return dp_local.parse(str(e.get("date", ""))).date()
                except Exception:
                    return date.min

            all_entries.sort(key=_date_key)

            if all_entries:
                try:
                    first = dp_local.parse(str(all_entries[0]["date"])).date()
                    last = dp_local.parse(str(all_entries[-1]["date"])).date()
                    span_days = (last - first).days
                except Exception:
                    span_days = 0

                if span_days <= settings.MULTISHEET_SPAN_DAYS:
                    return {
                        "employee_name": employee_name,
                        "period_start": all_entries[0]["date"],
                        "period_end": all_entries[-1]["date"],
                        "entries": all_entries,
                    }

        # Pick single best sheet
        best: Optional[Dict] = None
        best_count = 0
        for sheet in sheet_results:
            if len(sheet["entries"]) > best_count:
                best = sheet
                best_count = len(sheet["entries"])

        return best

    def _find_header_row(self, rows: List) -> tuple:
        for i, row in enumerate(rows[:15]):
            row_lower = [str(c or "").lower().replace("\n", " ") for c in row]
            matches = sum(1 for kw in HEADER_KEYWORDS if any(kw in cell for cell in row_lower))
            if matches >= 2:
                return i, row
        return None, None

    def _map_row(self, columns: List[str], row: List) -> Optional[Dict[str, Any]]:
        entry: Dict[str, Any] = {
            "date": None, "in_time": None, "out_time": None,
            "break_minutes": 0, "hours": None, "entry_type": "WORK",
            "leave_type": None, "source": "FILE_EXTRACTED",
        }

        for i, col in enumerate(columns):
            val = str(row[i] if i < len(row) else "").strip()
            if not val or val.lower() in ("nan", "none", "", "-", "n/a"):
                continue

            col_n = col.replace("\n", " ").strip().lower()

            # Detect invalid Excel epoch dates
            if val.startswith("INVALID_"):
                # Preserve the flag so validation can fire INVALID_DATE rule
                if col_n in ("date", "work date") or re.search(r"\bdate\b", col_n):
                    entry["date"] = val  # kept as-is; validation will flag it
                continue

            if col_n in ("date", "work date", "date of work") or (
                re.search(r"\bdate\b", col_n) and "update" not in col_n
            ):
                if entry["date"] is None:
                    entry["date"] = self._parse_date(val)

            elif col_n in ("in", "time in", "clock in", "start", "start time", "in time") or \
                 re.search(r"\bin\b(?! out)", col_n):
                if not entry["in_time"] and re.search(r"\d+:\d+", val):
                    entry["in_time"] = self._parse_time(val)

            elif col_n in ("out", "time out", "clock out", "end", "end time", "out time") or \
                 re.search(r"\bout\b", col_n):
                if not entry["out_time"] and re.search(r"\d+:\d+", val):
                    entry["out_time"] = self._parse_time(val)

            elif any(kw in col_n for kw in BREAK_KEYWORDS):
                entry["break_minutes"] = self._parse_break(val)

            elif re.search(r"regular\s*(?:billable\s*)?hrs?|regular\s*(?:billable\s*)?hours?", col_n):
                try:
                    f = float(re.sub(r"[^\d.]", "", val))
                    if f > 0 and entry["hours"] is None:
                        entry["hours"] = f
                except ValueError:
                    pass

            elif re.search(r"billable\s*hrs?|billable\s*hours?", col_n):
                try:
                    f = float(re.sub(r"[^\d.]", "", val))
                    if f > 0 and entry["hours"] is None:
                        entry["hours"] = f
                except ValueError:
                    pass

            elif re.search(r"daily\s*total|total\s*hrs?|total\s*hours?", col_n):
                try:
                    f = float(re.sub(r"[^\d.]", "", val))
                    if f >= 0:
                        entry["hours"] = f
                except ValueError:
                    pass

            elif re.search(r"\bhrs?\b|\bhours?\b|\bworked\b", col_n):
                try:
                    f = float(re.sub(r"[^\d.]", "", val))
                    if f > 0 and entry["hours"] is None:
                        entry["hours"] = f
                except ValueError:
                    pass

            elif any(kw in col_n for kw in ("leave", "type", "category", "sick", "vacation", "pto", "absence", "status")):
                upper = val.upper().strip()
                lower = val.lower().strip()
                leave_tokens = settings.leave_type_tokens
                # Check if the cell value is a leave-type token
                if lower in leave_tokens or upper in leave_tokens:
                    entry["entry_type"] = "LEAVE"
                    entry["leave_type"] = val.upper() if len(val) <= 10 else val
                elif re.search(r"\bholiday\b|\bph\b|\bpublic\b", lower):
                    entry["entry_type"] = "HOLIDAY"
                    entry["hours"] = entry["hours"] or 0.0
                elif re.search(r"sick", col_n):
                    try:
                        f = float(re.sub(r"[^\d.]", "", val))
                        if f > 0:
                            entry["entry_type"] = "LEAVE"
                            entry["leave_type"] = "SICK"
                            entry["hours"] = f
                    except ValueError:
                        pass
                elif re.search(r"vacation|pto|annual|privilege|casual|earned|flexi", col_n):
                    try:
                        f = float(re.sub(r"[^\d.]", "", val))
                        if f > 0:
                            entry["entry_type"] = "LEAVE"
                            entry["leave_type"] = col_n.split()[0].upper()[:10]
                            entry["hours"] = f
                    except ValueError:
                        pass

        return entry if entry["date"] else None

    # ── Text heuristics ───────────────────────────────────────────────────────

    def _normalize_text(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Pattern-match dates and hours from raw text lines."""
        entries = []
        lines = raw_text.split("\n")
        date_pat = re.compile(
            r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4}"
            r"|\d{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{4})",
            re.IGNORECASE,
        )

        for line in lines:
            date_match = date_pat.search(line)
            if not date_match:
                continue
            work_date = self._parse_date(date_match.group(0))
            if not work_date:
                continue

            hours_match = re.search(r"\b(\d+\.?\d*)\s*(?:hrs?|hours?)\b", line, re.IGNORECASE)
            hours = float(hours_match.group(1)) if hours_match else None

            time_matches = re.findall(r"\b(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\b", line)
            in_time = self._parse_time(time_matches[0]) if len(time_matches) >= 1 else None
            out_time = self._parse_time(time_matches[1]) if len(time_matches) >= 2 else None

            entries.append({
                "date": work_date,
                "in_time": in_time,
                "out_time": out_time,
                "break_minutes": 0,
                "hours": hours,
                "entry_type": "WORK",
                "leave_type": None,
                "source": "FILE_EXTRACTED",
            })

        if entries:
            employee_name = self._find_employee_name_from_text(raw_text)
            return {
                "employee_name": employee_name,
                "period_start": entries[0]["date"],
                "period_end": entries[-1]["date"],
                "entries": entries,
            }
        return None

    # ── Helper methods ────────────────────────────────────────────────────────

    @staticmethod
    def _clean_employee_name(name: Optional[str]) -> Optional[str]:
        """Strip trailing/leading non-name words from an extracted employee name.

        Handles:
        - "Muthuraj Anbalagan Week Start" → "Muthuraj Anbalagan"
        - "Muddada, Bharath" → "Bharath Muddada"
        - "JOHN SMITH" (all-caps) → "John Smith"
        - "Mary-Jane O'Brien" → preserved
        - Single word after stripping → rejected (ambiguous)
        """
        if not name:
            return None

        # Handle "Last, First" format → "First Last"
        comma_match = re.match(
            r"^([A-Za-z][A-Za-z\-\']+),\s+([A-Za-z][A-Za-z\-\' ]+)$",
            name.strip()
        )
        if comma_match:
            name = f"{comma_match.group(2).strip()} {comma_match.group(1).strip()}"

        # Convert ALL-CAPS names to Title Case (e.g. "JOHN SMITH" → "John Smith")
        words_check = name.strip().split()
        if words_check and all(w.isupper() or not w.isalpha() for w in words_check if w.isalpha()):
            name = name.title()

        # Normalise whitespace
        name = re.sub(r"\s+", " ", name.strip())

        # Remove standalone 4-digit years and pure-digit tokens
        name = re.sub(r"\b\d{4}\b", "", name)
        name = re.sub(r"\b\d+\b", "", name)
        name = re.sub(r"\s+", " ", name).strip()

        garbage = _get_garbage_words()

        # Strip trailing then leading garbage words
        words = name.split()
        original_word_count = len(words)
        while words and words[-1].lower() in garbage:
            words.pop()
        while words and words[0].lower() in garbage:
            words.pop(0)

        cleaned = " ".join(words)

        # Accept words that start with a capital letter (handles hyphens, apostrophes)
        # e.g. "O'Brien", "Van-Der", "McDonald"
        proper = [
            w for w in cleaned.split()
            if re.match(r"^[A-Z]", w) and re.search(r"[a-zA-Z]", w)
        ]
        if len(proper) < 1:
            return None

        # If original had ≥2 words but stripping leaves only 1 word, reject as ambiguous
        if original_word_count >= 2 and len(words) == 1:
            return None

        _reject_phrases = {
            "monthly time record", "weekly time record", "daily time record",
            "time sheet", "time record", "regular hours", "total hours",
            "employee name", "employee signature", "prepared by",
        }
        if cleaned.lower() in _reject_phrases:
            return None

        return cleaned if len(cleaned) > 2 else None

    @staticmethod
    def _parse_date(val: str) -> Optional[str]:
        from dateutil import parser as dp
        try:
            return dp.parse(str(val), dayfirst=False).strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _parse_time(val: str) -> Optional[str]:
        """Parse time to HH:MM 24h. Assumes 1–7 (no AM/PM) in work context = PM."""
        from dateutil import parser as dp
        try:
            val_str = str(val).strip()
            if val_str in ("0", "0:0", "0:00", "00:00", "00:00:00", "0:00:00"):
                return None
            t = dp.parse(val_str)
            if t.hour == 0 and t.minute == 0:
                return None
            if 0 < t.hour < 8 and not any(m in val_str.upper() for m in ("AM", "A.M", "PM", "P.M")):
                t = t.replace(hour=t.hour + 12)
            return t.strftime("%H:%M")
        except Exception:
            return None

    @staticmethod
    def _parse_break(val: str) -> int:
        try:
            clean = re.sub(r"[^\d.]", "", val)
            if not clean:
                return 0
            f = abs(float(clean))
            return int(f * 60) if f < 10 else int(f)
        except Exception:
            return 0

    @staticmethod
    def _find_employee_name(header_rows: List) -> Optional[str]:
        """Extract employee name from header rows above the column-header row."""
        # Generic label patterns — no company-specific words
        _addr_noise = {
            "court", "ave", "blvd", "street", "drive", "road", "lane", "place",
            "circle", "way", "boulevard", "parkway",
            "timesheets", "timesheet", "gmail", "yahoo", "hotmail", "phone",
            "week ending", "month starting", "month ending",
            "client", "manager", "supervisor", "approver",
        } | settings.company_stopwords

        # Pattern 1 — explicit label like "Employee: John Smith" or "Worker: ..."
        for row in header_rows:
            row_text = " ".join(str(c or "") for c in row if c)
            match = re.search(
                r"(?:employee|name|staff|worker|consultant|contractor|prepared\s*by)"
                r"[:\s]+([A-Za-z][A-Za-z\-\' ]{2,})",
                row_text, re.IGNORECASE,
            )
            if match:
                cand = match.group(1).strip()
                # Reject if it looks like an address or company token
                if not any(tok in cand.lower() for tok in _addr_noise):
                    return cand

        # Pattern 2 — standalone proper name cell at end of a header row
        for row in header_rows:
            cells = [str(c).strip() for c in row if str(c or "").strip()]
            if not cells:
                continue
            last_cell = cells[-1]
            if re.search(r"[@\d/\-:]", last_cell):
                continue
            if any(kw in last_cell.lower() for kw in _addr_noise):
                continue
            # Accept "First Last" or "FIRST LAST" or "Last, First" patterns
            m = re.match(
                r"^([A-Z][A-Za-z\-\']{1,}\s+[A-Z][A-Za-z\-\']{1,}(?:\s+[A-Z][A-Za-z\-\']{1,})?)$",
                last_cell.strip()
            )
            if m:
                return m.group(1).strip()

        return None

    @staticmethod
    def _find_employee_name_from_text(raw_text: str) -> Optional[str]:
        """Scan raw text for label→name patterns. Generic, no company specifics."""
        if not raw_text:
            return None
        # Pattern 1 — explicit label
        match = re.search(
            r"(?:employee|name|staff|worker|prepared\s*by|consultant|contractor"
            r"|submitted\s*by|timesheet\s*for|for\s*employee)[:\s]+([A-Za-z][A-Za-z\-\' ]{2,})",
            raw_text, re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().split("\n")[0].strip()

        # Pattern 2 — "Name Surname | Employee signature" line
        sig_match = re.search(
            r"([A-Za-z][A-Za-z\-\' ]{2,})\s*\|?\s*Employee\s+(?:signature|sign)",
            raw_text, re.IGNORECASE,
        )
        if sig_match:
            return sig_match.group(1).strip()

        # Pattern 3 — name on line before/after "Employee signature" label
        lines = raw_text.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"employee\s+(?:signature|sign)", line, re.IGNORECASE):
                # Check same line parts
                parts = re.split(r"\|", line)
                for part in parts:
                    m = re.search(
                        r"([A-Za-z][A-Za-z\-\' ]{2,})", part.strip()
                    )
                    if m and not re.search(
                        r"employee|signature|date|manager|supervisor", m.group(1), re.IGNORECASE
                    ):
                        return m.group(1).strip()
                # Previous line
                if i > 0:
                    prev = lines[i - 1].strip()
                    m = re.search(r"([A-Za-z][A-Za-z\-\' ]{5,})", prev)
                    if m and not re.search(
                        r"employee|signature|date|manager", m.group(1), re.IGNORECASE
                    ):
                        return m.group(1).strip()
        return None

    @staticmethod
    def _find_employee_name_from_filename(file_path: str) -> Optional[str]:
        """Extract employee name from a filename.

        Works generically — strips known garbage tokens (months, years, company
        stopwords loaded from config) and returns whatever proper name remains.

        Examples:
          "AJACE Timesheets Susan Savage.pdf" → "Susan Savage"
          "Bharath_TS_April_2026.pdf"         → "Bharath" (single — rejected)
          "Richard Watson April 2026.xlsx"    → "Richard Watson"
          "employee_John_Smith_may2026.pdf"   → "John Smith"
        """
        import os
        name = os.path.splitext(os.path.basename(file_path))[0]

        # Replace separators with spaces
        name = re.sub(r"[_\-]+", " ", name)

        # Strip months, years, dates
        name = re.sub(
            r"(?i)\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
            r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
            " ", name
        )
        name = re.sub(r"\b\d{4}\b|\b\d{1,2}[-/]\d{1,2}\b", " ", name)

        # Strip generic doc-type words AND company stopwords from config
        garbage = _get_garbage_words()
        words = name.split()
        words = [w for w in words if w.lower() not in garbage]
        name = " ".join(words).strip()

        # Extract a proper name (≥2 capitalised words)
        # Also handles all-caps like "JOHN SMITH" → title-cased
        name_tc = name.title() if name.isupper() else name
        match = re.search(
            r"([A-Z][A-Za-z\-\']{1,}(?:\s+[A-Z][A-Za-z\-\']{1,})+)",
            name_tc
        )
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_period_from_header(header_rows: List) -> tuple:
        from dateutil import parser as dp
        text = " ".join(" ".join(str(c or "") for c in row) for row in header_rows)
        start = end = None
        start_match = re.search(
            r"(?:starting|start|from|period start)[:\s]+(\d{1,2}[-/]\w+[-/]\d{4}|\d{4}-\d{2}-\d{2})",
            text, re.IGNORECASE,
        )
        end_match = re.search(
            r"(?:ending|end|to|period end)[:\s]+(\d{1,2}[-/]\w+[-/]\d{4}|\d{4}-\d{2}-\d{2})",
            text, re.IGNORECASE,
        )
        try:
            if start_match:
                start = dp.parse(start_match.group(1)).strftime("%Y-%m-%d")
            if end_match:
                end = dp.parse(end_match.group(1)).strftime("%Y-%m-%d")
        except Exception:
            pass
        return start, end

    @staticmethod
    def _best_candidate(candidates: List[Dict]) -> Optional[Dict]:
        """Pick the result with the most valid entries (prefer entries with hours)."""
        if not candidates:
            return None

        def _score(c):
            entries = c.get("entries") or []
            has_hours = sum(
                1 for e in entries
                if (e.get("hours") is not None) or (e.get("in_time") and e.get("out_time"))
            )
            return (len(entries), has_hours, bool(c.get("employee_name")))

        return max(candidates, key=_score)

    @staticmethod
    def _score_result(result: Dict[str, Any]) -> float:
        """Score 0–1 based on completeness of extracted data."""
        score = 0.0
        if result.get("employee_name"):
            score += 0.25
        if result.get("period_start"):
            score += 0.05
        if result.get("period_end"):
            score += 0.05
        entries = result.get("entries", [])
        if entries:
            score += 0.25
            dated = sum(1 for e in entries if e.get("date"))
            score += 0.2 * (dated / len(entries))
            with_hours = sum(1 for e in entries if e.get("hours") or (e.get("in_time") and e.get("out_time")))
            score += 0.2 * (with_hours / len(entries))
        return min(score, 1.0)

    @staticmethod
    def _clean_entries(result: Dict[str, Any]) -> Dict[str, Any]:
        """Remove outlier dates and ghost entries with no useful data."""
        entries = result.get("entries", [])
        if len(entries) < 3:
            return result

        from dateutil import parser as dp

        # Drop ghost entries (no in_time, no out_time, no hours)
        meaningful = []
        ghost_dates: set = set()
        for e in entries:
            has_time = e.get("in_time") or e.get("out_time")
            has_hours = e.get("hours") is not None and float(e.get("hours") or 0) > 0
            if has_time or has_hours:
                meaningful.append(e)
            else:
                ghost_dates.add(e.get("date"))

        real_dates = {e.get("date") for e in meaningful}
        for e in entries:
            if e.get("date") in ghost_dates and e.get("date") not in real_dates:
                meaningful.append(e)
                real_dates.add(e.get("date"))

        def _sort_key(e):
            d = e.get("date")
            if not d:
                return ""
            try:
                return dp.parse(str(d)).strftime("%Y-%m-%d")
            except Exception:
                return str(d)

        meaningful.sort(key=_sort_key)
        entries = meaningful if meaningful else entries

        # Remove date outliers (signature dates, wrong-year entries)
        parsed_dates = []
        for e in entries:
            d = e.get("date")
            if d:
                try:
                    parsed_dates.append(dp.parse(str(d)).date() if isinstance(d, str) else d)
                except Exception:
                    pass

        if not parsed_dates:
            return result

        sorted_dates = sorted(parsed_dates)
        median_date = sorted_dates[len(sorted_dates) // 2]
        threshold_days = settings.DATE_OUTLIER_THRESHOLD_DAYS

        cleaned = []
        for e in entries:
            d = e.get("date")
            if not d:
                continue
            try:
                d_obj = dp.parse(str(d)).date() if isinstance(d, str) else d
                if abs((d_obj - median_date).days) <= threshold_days:
                    cleaned.append(e)
            except Exception:
                cleaned.append(e)

        if cleaned:
            result["entries"] = cleaned
            result["period_start"] = cleaned[0]["date"]
            work_entries = [e for e in cleaned if e.get("in_time") or e.get("hours")]
            result["period_end"] = work_entries[-1]["date"] if work_entries else cleaned[-1]["date"]

        return result

    @staticmethod
    def _fix_times(result: Dict[str, Any]) -> Dict[str, Any]:
        """Fix AM/PM ambiguity: if out < in and out is before noon, assume PM."""
        entries = result.get("entries", [])
        for entry in entries:
            in_t = entry.get("in_time")
            out_t = entry.get("out_time")
            if in_t and out_t:
                try:
                    in_h, in_m = map(int, in_t.split(":"))
                    out_h, out_m = map(int, out_t.split(":"))
                    in_mins = in_h * 60 + in_m
                    out_mins = out_h * 60 + out_m
                    if out_mins < in_mins and out_h < 12:
                        entry["out_time"] = f"{out_h + 12:02d}:{out_m:02d}"
                except Exception:
                    pass
        return result

    def _log(self, file_id: str, stage: str, status: str, message: str) -> None:
        log = FileProcessingLog(id=gen_uuid(), file_id=file_id,
                                stage=stage, status=status, message=message)
        self.db.add(log)
        self.db.commit()

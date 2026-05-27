"""
TimesheetRuleParser — deterministic extraction + validation.

Takes the raw text output from VLMService (plain OCR lines) and produces a
validated timesheet result dict.  No LLM inference happens here; everything is
rule-based regex + arithmetic so results are reproducible and auditable.

Output schema
─────────────
{
  "employee_name":          str | None,
  "employee_id":            str | None,
  "department":             str | None,
  "manager":                str | None,
  "company":                str | None,
  "period":                 str | None,       # human-readable e.g. "May 2026"
  "period_start":           str | None,       # YYYY-MM-DD
  "period_end":             str | None,       # YYYY-MM-DD
  "approval_status":        str | None,
  "submitted_total_hours":  float | None,
  "approved_total_hours":   float | None,
  "calculated_total_hours": float,            # sum of accepted entry hours
  "payroll_hours_to_use":   float,            # approved > submitted > calculated
  "entries":                list[dict],       # accepted rows only
  "rejected_entries":       list[dict],       # rows that failed validation
  "entries_found":          int,
  "needs_hr_review":        bool,
  "review_reasons":         list[str],
}
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Regex building blocks ──────────────────────────────────────────────────────

# Date patterns — order matters; most specific first
_DATE_PATTERNS: List[Tuple[str, str]] = [
    # ISO: 2026-05-19
    (r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",         "%Y-%m-%d"),
    # DD/MM/YYYY or DD-MM-YYYY
    (r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b",          None),
    # Mon DD YYYY  /  DD Mon YYYY  /  Mon DD, YYYY
    (r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b", None),
    (r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b", None),
    # DD Mon  (no year — will use period year)
    (r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?)\b", None),
]

_MONTHS = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}
_MONTH_NAMES = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

_HOUR_NUM   = r"(\d{1,2}(?:\.\d{1,2})?)"          # 8 or 8.5
_TIME_HHMM  = r"(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)"
_DAYS_RE    = re.compile(
    r"\b(Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|"
    r"Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\b", re.I
)

# Keywords that precede employee name — stops at double-space (column separator),
# another "Label:" pattern, or end-of-line.
_EMP_LABELS = re.compile(
    r"(?:employee(?:\s*\w*)?|name|staff|worker|associate)"
    r"\s*[:\-–]\s*([A-Za-z][A-Za-z '\.\-]+?)(?=\s{2,}|[A-Z][a-z]+\s*[:\-–]|\n|$)",
    re.I,
)
_EMP_ID_LABELS = re.compile(
    r"(?:employee\s*id|staff\s*id|id|badge|payroll\s*no?\.?)"
    r"\s*[:\-–#]\s*([A-Z0-9\-/]{2,20})",
    re.I,
)
_DEPT_LABELS = re.compile(
    r"(?:department|dept\.?|division|team)\s*[:\-–]\s*([A-Za-z][A-Za-z0-9\s\-&]+?)(?=\s{2,}|[A-Z][a-z]+\s*[:\-–]|\n|$)", re.I
)
_MGR_LABELS = re.compile(
    r"(?:manager|supervisor|approver|approved\s+by)\s*[:\-–]\s*([A-Za-z][A-Za-z '\.\-]+?)(?=\s{2,}|[A-Z][a-z]+\s*[:\-–]|\n|$)", re.I
)
_COMPANY_LABELS = re.compile(
    r"(?:company|organisation|organization|employer)\s*[:\-–]\s*([A-Za-z][A-Za-z0-9\s\-&\.]+?)(?=\s{2,}|[A-Z][a-z]+\s*[:\-–]|\n|$)", re.I
)

# Approval status
_APPROVAL_RE = re.compile(
    r"\b(approved|pending\s+approval|pending|rejected|submitted|draft|authorized)\b", re.I
)

# Totals
_TOTAL_RE = re.compile(
    r"\b(?:total|grand\s+total|total\s+hours?|hours?\s+total)\s*[:\-–]?\s*"
    + _HOUR_NUM,
    re.I,
)
_APPROVED_TOTAL_RE = re.compile(
    r"\b(?:approved\s+(?:total\s+)?hours?|hours?\s+approved|approved\s+total)"
    r"\s*[:\-–]?\s*" + _HOUR_NUM,
    re.I,
)
_SUBMITTED_TOTAL_RE = re.compile(
    r"\b(?:submitted\s+(?:total\s+)?hours?|hours?\s+submitted)\s*[:\-–]?\s*"
    + _HOUR_NUM,
    re.I,
)

# Period / date range
_PERIOD_RANGE_RE = re.compile(
    r"\b(?:period|pay\s*period|week|fortnight|month)\s*[:\-–]?\s*"
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s*(?:to|[-–—])\s*"
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    re.I,
)
_DATE_RANGE_RE = re.compile(
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s*(?:to|[-–—])\s*"
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})"
)


# ── Public API ─────────────────────────────────────────────────────────────────

class TimesheetRuleParser:
    """Stateless rule-based parser.  Call TimesheetRuleParser.parse(raw_text)."""

    @classmethod
    def parse(cls, raw_text: str) -> Dict[str, Any]:
        """Parse raw OCR text into a validated timesheet dict."""
        lines  = [ln.rstrip() for ln in raw_text.splitlines()]
        result: Dict[str, Any] = {}

        # ── 1. Header fields ──────────────────────────────────────────────────
        result["employee_name"] = cls._find_label(_EMP_LABELS,     lines)
        result["employee_id"]   = cls._find_label(_EMP_ID_LABELS,  lines)
        result["department"]    = cls._find_label(_DEPT_LABELS,    lines)
        result["manager"]       = cls._find_label(_MGR_LABELS,     lines)
        result["company"]       = cls._find_label(_COMPANY_LABELS, lines)

        # ── 2. Approval status ────────────────────────────────────────────────
        result["approval_status"] = cls._find_approval_status(lines)

        # ── 3. Period / date range ────────────────────────────────────────────
        period_start, period_end, period_str = cls._find_period(raw_text, lines)
        result["period"]       = period_str
        result["period_start"] = _fmt_date(period_start)
        result["period_end"]   = _fmt_date(period_end)

        # ── 4. Submitted / approved totals ────────────────────────────────────
        submitted = cls._find_hours_total(_SUBMITTED_TOTAL_RE, raw_text)
        approved  = cls._find_hours_total(_APPROVED_TOTAL_RE,  raw_text)

        # Fallback: "Total: 40.0" without qualifier → submitted total
        if submitted is None:
            submitted = cls._find_hours_total(_TOTAL_RE, raw_text)

        result["submitted_total_hours"] = submitted
        result["approved_total_hours"]  = approved

        # ── 5. Parse table rows ───────────────────────────────────────────────
        raw_entries = cls._parse_table_rows(lines, period_start, period_end)

        # ── 6. Validate rows ──────────────────────────────────────────────────
        accepted, rejected, review_reasons = cls._validate_rows(
            raw_entries, period_start, period_end, submitted
        )

        # ── 7. Calculated total ───────────────────────────────────────────────
        calc_total = round(
            sum(float(e.get("hours") or e.get("regular_hours") or 0) for e in accepted),
            2,
        )

        # ── 8. Payroll hours decision ─────────────────────────────────────────
        #  Priority: approved → submitted → calculated
        #  If approved != submitted → flag for HR review
        payroll_hours, extra_reasons = cls._decide_payroll_hours(
            calc_total, submitted, approved
        )
        review_reasons.extend(extra_reasons)

        needs_review = bool(review_reasons)

        result.update({
            "entries":                accepted,
            "rejected_entries":       rejected,
            "entries_found":          len(accepted),
            "calculated_total_hours": calc_total,
            "payroll_hours_to_use":   payroll_hours,
            "needs_hr_review":        needs_review,
            "review_reasons":         review_reasons,
        })
        return result

    # ── Header extraction ──────────────────────────────────────────────────────

    @staticmethod
    def _find_label(pattern: re.Pattern, lines: List[str]) -> Optional[str]:
        for line in lines:
            m = pattern.search(line)
            if m:
                val = m.group(1).strip().strip(".,;:")
                if len(val) > 1:
                    return val
        return None

    @staticmethod
    def _find_approval_status(lines: List[str]) -> Optional[str]:
        for line in lines:
            m = _APPROVAL_RE.search(line)
            if m:
                return m.group(1).lower()
        return None

    # ── Period detection ───────────────────────────────────────────────────────

    @classmethod
    def _find_period(
        cls, raw_text: str, lines: List[str]
    ) -> Tuple[Optional[date], Optional[date], Optional[str]]:
        # Try explicit "Period: DD/MM/YYYY to DD/MM/YYYY"
        m = _PERIOD_RANGE_RE.search(raw_text)
        if not m:
            m = _DATE_RANGE_RE.search(raw_text)
        if m:
            d1 = _parse_date_str(m.group(1))
            d2 = _parse_date_str(m.group(2))
            if d1 and d2:
                period_str = f"{_fmt_date(d1)} to {_fmt_date(d2)}"
                return d1, d2, period_str

        # Try "May 2026" or "April 2026" as period → treat as full month
        month_year = re.search(
            r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+(\d{4})\b", raw_text, re.I
        )
        if month_year:
            mo_str = month_year.group(1).lower()[:3]
            mo     = _MONTHS.get(mo_str)
            yr     = int(month_year.group(2))
            if mo:
                import calendar
                last_day = calendar.monthrange(yr, mo)[1]
                d1 = date(yr, mo, 1)
                d2 = date(yr, mo, last_day)
                period_str = f"{month_year.group(1)} {yr}"
                return d1, d2, period_str

        # Week number: "Week 21, 2026"
        wk = re.search(r"\bweek\s*(\d{1,2})[,\s]+(\d{4})\b", raw_text, re.I)
        if wk:
            week_num = int(wk.group(1))
            yr       = int(wk.group(2))
            try:
                d1 = date.fromisocalendar(yr, week_num, 1)
                d2 = d1 + timedelta(days=6)
                return d1, d2, f"Week {week_num}, {yr}"
            except ValueError:
                pass

        return None, None, None

    # ── Totals ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _find_hours_total(pattern: re.Pattern, text: str) -> Optional[float]:
        for m in pattern.finditer(text):
            try:
                val = float(m.group(1))
                if 0 < val <= 744:   # max hours in a month (31 days × 24)
                    return round(val, 2)
            except (ValueError, IndexError):
                pass
        return None

    # ── Table row parsing ──────────────────────────────────────────────────────

    @classmethod
    def _parse_table_rows(
        cls,
        lines: List[str],
        period_start: Optional[date],
        period_end:   Optional[date],
    ) -> List[Dict[str, Any]]:
        """
        Scan every line; if a date is present, treat the line as a data row.
        Try to extract: date, day, start_time, end_time, break, regular_hours,
        overtime_hours, total_hours, task/notes.
        """
        entries: List[Dict] = []
        for line in lines:
            row = cls._extract_row(line)
            if row:
                entries.append(row)
        return entries

    @classmethod
    def _extract_row(cls, line: str) -> Optional[Dict[str, Any]]:
        """Return an entry dict if the line looks like a timesheet data row."""
        # Must contain a date to be considered a data row
        dt = _find_first_date(line)
        if dt is None:
            return None

        # Day of week
        day_m = _DAYS_RE.search(line)
        day   = day_m.group(1).capitalize() if day_m else None

        # Times  HH:MM
        times = re.findall(_TIME_HHMM, line)
        start_time = times[0] if len(times) >= 1 else None
        end_time   = times[1] if len(times) >= 2 else None

        # All standalone decimal/integer numbers on the line
        # (after removing date-like strings and times to avoid double counting)
        stripped = line
        stripped = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", "", stripped)
        stripped = re.sub(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}",  "", stripped)
        stripped = re.sub(_TIME_HHMM,                          "", stripped)
        stripped = re.sub(r"\b\d{1,2}[-/]\d{1,2}\b",          "", stripped)
        # Keep ALL numeric values here; the validator flags impossible ones (>24)
        nums = [float(x) for x in re.findall(r"\b(\d{1,2}(?:\.\d{1,2})?)\b", stripped)]

        # Heuristic assignment based on number of numeric columns found:
        #   1 number  → that IS total hours
        #   2 numbers → regular + overtime (total = reg + ot)
        #   3+ numbers → reg, ot, total (last is the stated total)
        regular_hours  = None
        overtime_hours = None
        total_hours    = None

        # Filter out zero-only values if there are non-zero ones
        non_zero = [n for n in nums if n > 0]
        working_nums = non_zero if non_zero else nums

        if len(working_nums) == 1:
            total_hours   = working_nums[0]
            regular_hours = working_nums[0]
        elif len(working_nums) == 2:
            regular_hours  = working_nums[0]
            overtime_hours = nums[1]   # preserve original (may be 0.0)
            total_hours    = round(working_nums[0] + (nums[1] if nums[1] > 0 else 0), 2)
        elif len(working_nums) >= 3:
            regular_hours  = working_nums[-3]
            overtime_hours = working_nums[-2]
            total_hours    = working_nums[-1]

        # Fallback: calculate from start/end times if no numeric hours found
        if total_hours is None and start_time and end_time:
            total_hours = _hours_from_times(start_time, end_time)
            regular_hours = total_hours

        if total_hours is None:
            return None   # no hours info → not a real data row

        # Task / notes: keep alphanumeric tokens (including codes like PROJ-101)
        # Remove digits that look like standalone numbers (hours, break mins)
        task_text = re.sub(r"(?<![A-Z\w])\d+(?:\.\d+)?(?![A-Z\w])", "", stripped, flags=re.I)
        task_text = re.sub(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", "", task_text, flags=re.I)
        task_text = re.sub(r"\s+", " ", task_text).strip().strip(".,;:-|")
        task      = task_text if len(task_text) > 2 else None

        return {
            "date":            _fmt_date(dt),
            "day":             day,
            "start_time":      start_time,
            "end_time":        end_time,
            "regular_hours":   regular_hours,
            "overtime_hours":  overtime_hours,
            "hours":           total_hours,
            "task":            task,
        }

    # ── Validation ─────────────────────────────────────────────────────────────

    @classmethod
    def _validate_rows(
        cls,
        entries:      List[Dict],
        period_start: Optional[date],
        period_end:   Optional[date],
        submitted_total: Optional[float],
    ) -> Tuple[List[Dict], List[Dict], List[str]]:
        accepted: List[Dict] = []
        rejected: List[Dict] = []
        reasons:  List[str]  = []

        for entry in entries:
            reject_reason = cls._check_row(entry, period_start, period_end)
            if reject_reason:
                entry["_reject_reason"] = reject_reason
                rejected.append(entry)
            else:
                accepted.append(entry)

        # Check calculated vs submitted total
        if submitted_total is not None and accepted:
            calc = round(sum(float(e.get("hours") or 0) for e in accepted), 2)
            diff = round(abs(calc - submitted_total), 2)
            if diff > 0.25:           # allow 15-min rounding tolerance
                reasons.append(
                    f"Calculated hours ({calc}h) differ from submitted total "
                    f"({submitted_total}h) by {diff}h — manual check required."
                )

        if rejected:
            reasons.append(
                f"{len(rejected)} row(s) rejected: "
                + "; ".join(set(e.get("_reject_reason", "?") for e in rejected))
            )

        return accepted, rejected, reasons

    @staticmethod
    def _check_row(
        entry:        Dict,
        period_start: Optional[date],
        period_end:   Optional[date],
    ) -> Optional[str]:
        """Return a rejection reason string, or None if row is valid."""
        date_str = entry.get("date")
        hours    = float(entry.get("hours") or 0)

        # Impossible hours
        if hours > 24:
            return f"Impossible hours ({hours}h > 24h per day)"
        if hours <= 0:
            return "Zero or negative hours"

        if date_str and period_start and period_end:
            try:
                row_date = date.fromisoformat(date_str)
                if row_date < period_start or row_date > period_end:
                    return (
                        f"Date {date_str} is outside payroll period "
                        f"{_fmt_date(period_start)}–{_fmt_date(period_end)}"
                    )
            except ValueError:
                pass  # unparseable date — accept with warning

        return None

    # ── Payroll hours decision ─────────────────────────────────────────────────

    @staticmethod
    def _decide_payroll_hours(
        calc_total:  float,
        submitted:   Optional[float],
        approved:    Optional[float],
    ) -> Tuple[float, List[str]]:
        reasons: List[str] = []

        if approved is not None:
            if submitted is not None and abs(approved - submitted) > 0.25:
                reasons.append(
                    f"Approved total ({approved}h) differs from submitted total "
                    f"({submitted}h) — using approved total for payroll."
                )
            return approved, reasons

        if submitted is not None:
            return submitted, reasons

        # No totals visible — use calculated
        reasons.append(
            "No submitted or approved total found in document; "
            f"using calculated total ({calc_total}h)."
        )
        return calc_total, reasons


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_date(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _find_first_date(text: str) -> Optional[date]:
    """Return the first parseable date found in text, or None."""
    # ISO first (most reliable)
    m = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # DD/MM/YYYY or MM/DD/YYYY
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", text)
    if m:
        a, b, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Try DD/MM/YYYY first; if invalid try MM/DD/YYYY
        for day, mo in ((a, b), (b, a)):
            try:
                return date(yr, mo, day)
            except ValueError:
                pass

    # "19 May 2026" or "May 19, 2026"
    m = re.search(
        r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+(\d{4})\b", text, re.I
    )
    if m:
        mo_str = m.group(2).lower()[:3]
        mo     = _MONTHS.get(mo_str)
        if mo:
            try:
                return date(int(m.group(3)), mo, int(m.group(1)))
            except ValueError:
                pass

    m = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+(\d{1,2}),?\s+(\d{4})\b", text, re.I
    )
    if m:
        mo_str = m.group(1).lower()[:3]
        mo     = _MONTHS.get(mo_str)
        if mo:
            try:
                return date(int(m.group(3)), mo, int(m.group(2)))
            except ValueError:
                pass

    return None


def _parse_date_str(s: str) -> Optional[date]:
    """Parse a date string in common formats; return date or None."""
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d",
                "%d/%m/%y",  "%m/%d/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return _find_first_date(s)


def _hours_from_times(start: str, end: str) -> Optional[float]:
    """Compute hours between two HH:MM strings; return None on failure."""
    def _to_min(t: str) -> Optional[int]:
        t = t.strip().upper()
        pm = "PM" in t
        am = "AM" in t
        t  = t.replace("PM","").replace("AM","").strip()
        try:
            h, m = map(int, t.split(":"))
        except ValueError:
            return None
        if pm and h != 12:
            h += 12
        if am and h == 12:
            h = 0
        return h * 60 + m

    sm = _to_min(start)
    em = _to_min(end)
    if sm is None or em is None:
        return None
    diff = em - sm
    if diff < 0:
        diff += 24 * 60      # overnight shift
    return round(diff / 60, 2)

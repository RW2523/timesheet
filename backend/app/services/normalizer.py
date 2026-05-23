"""
Normalizer service — Phase 4.
Converts raw extraction text/tables into the standard timesheet JSON schema.
Deterministic mapping first; LLM cleanup second (if enabled).
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

# Common date patterns
DATE_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}",
    r"\d{2}/\d{2}/\d{4}",
    r"\d{2}-\d{2}-\d{4}",
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
]

TIME_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?\b")

HEADER_KEYWORDS = [
    "employee", "name", "date", "in time", "out time", "hours",
    "regular", "overtime", "leave", "holiday", "total",
]


class NormalizerService:
    def __init__(self, db: Session):
        self.db = db
        self.llm = LLMService()

    def normalize(self, raw_ext: RawExtraction) -> Optional[Dict[str, Any]]:
        """
        Attempt deterministic normalization; fall back to LLM if needed.
        Stores llm_json in RawExtraction and flags for review if confidence is low.
        """
        result = None
        method = "deterministic"

        # Step 1: Try deterministic mapping from tables
        if raw_ext.raw_tables:
            result = self._normalize_tables(raw_ext.raw_tables)

        # Step 2: If deterministic failed or partial, try LLM
        if (not result or not result.get("entries")) and self.llm.is_enabled() and raw_ext.raw_text:
            llm_result = self.llm.extract_timesheet_json(
                raw_ext.raw_text,
                file_metadata={"file_id": str(raw_ext.file_id)},
            )
            if llm_result and llm_result.get("entries"):
                result = llm_result
                method = "llm"

        # Step 3: If still nothing, try text heuristics
        if (not result or not result.get("entries")) and raw_ext.raw_text:
            result = self._normalize_text(raw_ext.raw_text)
            method = "text_heuristic"

        if result:
            raw_ext.llm_json = result
            # Flag low confidence for review
            confidence = self._score_result(result)
            raw_ext.confidence = confidence

            file = self.db.query(UploadedFile).filter(UploadedFile.id == raw_ext.file_id).first()
            if file:
                if confidence < settings.OCR_CONFIDENCE_THRESHOLD:
                    file.processing_status = "NEEDS_REVIEW"
                    self._log(str(raw_ext.file_id), "NORMALIZE", "LOW_CONFIDENCE",
                              f"Confidence {confidence:.2f} below threshold")
                else:
                    file.processing_status = "NORMALIZED"
                file.updated_at = datetime.utcnow()

            self.db.commit()
        else:
            # No extraction possible — flag for HR manual review
            file = self.db.query(UploadedFile).filter(UploadedFile.id == raw_ext.file_id).first()
            if file:
                file.processing_status = "NEEDS_REVIEW"
                file.updated_at = datetime.utcnow()
            self._log(str(raw_ext.file_id), "NORMALIZE", "FAILED", "No extractable data found")
            self.db.commit()

        return result

    def _normalize_tables(self, raw_tables: List[Dict]) -> Optional[Dict[str, Any]]:
        """Deterministic column mapping from tabular data."""
        for table in raw_tables:
            rows = table.get("rows", [])
            if len(rows) < 2:
                continue

            # Find header row
            header_idx = None
            header_row = None
            for i, row in enumerate(rows[:5]):
                row_lower = [str(c).lower() for c in row]
                matches = sum(1 for kw in HEADER_KEYWORDS if any(kw in cell for cell in row_lower))
                if matches >= 2:
                    header_idx = i
                    header_row = row
                    break

            if header_idx is None:
                continue

            columns = [str(c).lower().strip() for c in header_row]
            entries = []

            for row in rows[header_idx + 1:]:
                if len(row) < 2:
                    continue
                entry = self._map_row(columns, row)
                if entry and entry.get("date"):
                    entries.append(entry)

            if entries:
                employee_name = self._find_employee_name(rows[:header_idx])
                return {
                    "employee_name": employee_name,
                    "period_start": entries[0]["date"] if entries else None,
                    "period_end": entries[-1]["date"] if entries else None,
                    "entries": entries,
                }
        return None

    def _map_row(self, columns: List[str], row: List) -> Optional[Dict[str, Any]]:
        """Map a row to a standardised entry dict using column headers."""
        entry: Dict[str, Any] = {
            "date": None, "in_time": None, "out_time": None,
            "break_minutes": 0, "hours": None, "entry_type": "WORK",
            "leave_type": None,
        }

        for i, col in enumerate(columns):
            val = str(row[i]).strip() if i < len(row) else ""
            if not val or val.lower() in ("nan", "none", ""):
                continue

            if any(kw in col for kw in ("date", "day")):
                entry["date"] = self._parse_date(val)
            elif any(kw in col for kw in ("in", "start", "clock in", "time in")):
                entry["in_time"] = self._parse_time(val)
            elif any(kw in col for kw in ("out", "end", "clock out", "time out")):
                entry["out_time"] = self._parse_time(val)
            elif any(kw in col for kw in ("break", "lunch")):
                entry["break_minutes"] = self._parse_break(val)
            elif any(kw in col for kw in ("hour", "total", "worked")):
                try:
                    entry["hours"] = float(val)
                except ValueError:
                    pass
            elif any(kw in col for kw in ("leave", "type", "category")):
                upper = val.upper()
                if upper in ("LEAVE", "SICK", "VACATION", "PTO"):
                    entry["entry_type"] = "LEAVE"
                    entry["leave_type"] = val
                elif upper in ("HOLIDAY",):
                    entry["entry_type"] = "HOLIDAY"

        return entry if entry["date"] else None

    def _normalize_text(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Heuristic text extraction when no table structure is found."""
        entries = []
        lines = raw_text.split("\n")

        for line in lines:
            date_match = re.search(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}", line)
            if not date_match:
                continue
            work_date = self._parse_date(date_match.group(0))
            if not work_date:
                continue

            hours_match = re.search(r"\b(\d+\.?\d*)\s*(?:hrs?|hours?)\b", line, re.IGNORECASE)
            hours = float(hours_match.group(1)) if hours_match else None

            entries.append({"date": work_date, "hours": hours, "entry_type": "WORK"})

        if entries:
            return {
                "employee_name": None,
                "period_start": entries[0]["date"],
                "period_end": entries[-1]["date"],
                "entries": entries,
            }
        return None

    @staticmethod
    def _parse_date(val: str) -> Optional[str]:
        """Parse various date formats to YYYY-MM-DD."""
        from dateutil import parser as dp
        try:
            return dp.parse(str(val), dayfirst=False).strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _parse_time(val: str) -> Optional[str]:
        """Parse time string to HH:MM (24h)."""
        from dateutil import parser as dp
        try:
            return dp.parse(str(val)).strftime("%H:%M")
        except Exception:
            return None

    @staticmethod
    def _parse_break(val: str) -> int:
        try:
            f = float(re.sub(r"[^\d.]", "", val))
            return int(f * 60) if f < 10 else int(f)
        except Exception:
            return 0

    @staticmethod
    def _find_employee_name(header_rows: List) -> Optional[str]:
        for row in header_rows:
            row_text = " ".join(str(c) for c in row if c)
            name_match = re.search(
                r"(?:employee|name|staff)[:\s]+([A-Z][a-z]+(?: [A-Z][a-z]+)+)",
                row_text,
                re.IGNORECASE,
            )
            if name_match:
                return name_match.group(1).strip()
        return None

    @staticmethod
    def _score_result(result: Dict[str, Any]) -> float:
        score = 0.0
        if result.get("employee_name"):
            score += 0.3
        if result.get("period_start"):
            score += 0.1
        entries = result.get("entries", [])
        if entries:
            score += 0.3
            dated = sum(1 for e in entries if e.get("date"))
            score += 0.3 * (dated / len(entries))
        return min(score, 1.0)

    def _log(self, file_id: str, stage: str, status: str, message: str) -> None:
        log = FileProcessingLog(id=gen_uuid(), file_id=file_id, stage=stage, status=status, message=message)
        self.db.add(log)
        self.db.commit()

"""
Employee match service — Phase 5.
Matches a file to an employee using exact then fuzzy matching.

Matching priority:
1. Employee ID from document (exact)
2. Employee email from document (exact)
3. Exact full name (case-insensitive)
4. Fuzzy full-name match (RapidFuzz token_sort_ratio)

Thresholds (configurable via settings):
- >= FUZZY_AUTO_THRESHOLD (0.85): AUTO_MATCHED
- >= FUZZY_REVIEW_THRESHOLD (0.60): NEEDS_REVIEW
- < FUZZY_REVIEW_THRESHOLD: NOT_MATCHED

No matched employee = payroll blocker (handled by ValidationService).
"""
import logging
import re
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any

from sqlalchemy.orm import Session
from rapidfuzz import fuzz

from app.core.config import settings
from app.db.models import (
    Employee, UploadedFile, RawExtraction, EmployeeFileMatch, gen_uuid,
)

logger = logging.getLogger(__name__)


def _get_name_garbage_tokens() -> set:
    """Build garbage token set from config (shared source of truth with normalizer)."""
    from app.core.config import settings
    base = {
        # File/period suffixes
        "ts", "timesheet", "timesheets", "time", "sheet", "record",
        "monthly", "weekly", "daily", "bi", "bimonthly",
        # Month names
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
        # File extensions
        "pdf", "csv", "xlsx", "docx", "doc", "xls",
    }
    return base | settings.company_stopwords


def _clean_name_for_matching(name: str) -> str:
    """Remove noise tokens and normalise whitespace for matching."""
    if not name:
        return ""
    # Remove 4-digit years
    cleaned = re.sub(r"\b\d{4}\b", "", name)
    # Remove numbers
    cleaned = re.sub(r"\b\d+\b", "", cleaned)
    # Normalise separators
    cleaned = re.sub(r"[_\-]+", " ", cleaned)
    # Remove noise tokens (word-boundary aware)
    garbage = _get_name_garbage_tokens()
    words = cleaned.split()
    words = [w for w in words if w.lower() not in garbage]
    # Convert ALL-CAPS to Title Case for better fuzzy comparison
    result = " ".join(words).strip()
    if result and result == result.upper():
        result = result.title()
    return result


class EmployeeMatchService:
    def __init__(self, db: Session):
        self.db = db

    def match_file(self, file_record: UploadedFile) -> Optional[str]:
        """Attempt to match the file to an employee.

        Returns employee_id if matched at any confidence, None if no candidate name.
        Sets match_status to AUTO_MATCHED, NEEDS_REVIEW, or NOT_MATCHED.
        """
        candidate_name = self._get_candidate_name(file_record)
        if not candidate_name:
            file_record.match_status = "NOT_MATCHED"
            file_record.processing_status = "NEEDS_REVIEW"
            self._record_match(file_record, None, None, "NO_NAME", 0.0, "NOT_MATCHED", [])
            self.db.commit()
            return None

        # Clean the name for better matching
        clean_name = _clean_name_for_matching(candidate_name)
        if not clean_name:
            logger.warning(f"Candidate name '{candidate_name}' reduced to empty after cleaning")
            file_record.match_status = "NOT_MATCHED"
            file_record.processing_status = "NEEDS_REVIEW"
            self._record_match(file_record, candidate_name, None, "EMPTY_AFTER_CLEAN", 0.0, "NOT_MATCHED", [])
            self.db.commit()
            return None

        employee_id, confidence, method, alternatives = self._find_match(clean_name)

        auto_threshold = settings.FUZZY_AUTO_THRESHOLD
        review_threshold = settings.FUZZY_REVIEW_THRESHOLD

        if employee_id and confidence >= auto_threshold:
            file_record.matched_employee_id = employee_id
            file_record.match_confidence = confidence
            file_record.match_status = "AUTO_MATCHED"
            # Keep processing_status from normalizer (NORMALIZED / COMPLETED)
            if file_record.processing_status in ("NORMALIZED", "COMPLETED"):
                file_record.processing_status = "MATCHED"
        elif employee_id and confidence >= review_threshold:
            file_record.matched_employee_id = employee_id
            file_record.match_confidence = confidence
            file_record.match_status = "NEEDS_REVIEW"
            file_record.processing_status = "NEEDS_REVIEW"
        else:
            file_record.match_status = "NOT_MATCHED"
            file_record.match_confidence = confidence
            # NOT_MATCHED is a payroll blocker — downgrade processing status
            file_record.processing_status = "NEEDS_REVIEW"
            employee_id = None

        file_record.updated_at = datetime.utcnow()
        self._record_match(
            file_record, candidate_name, employee_id, method,
            confidence, file_record.match_status, alternatives,
        )
        self.db.commit()
        return employee_id

    def _get_candidate_name(self, file_record: UploadedFile) -> Optional[str]:
        """Get best candidate name from extracted data or file path."""
        # Raw extraction JSON (LLM-extracted name — most reliable)
        raw = self.db.query(RawExtraction).filter(RawExtraction.file_id == file_record.id).first()
        if raw and raw.llm_json:
            name = raw.llm_json.get("employee_name")
            if name and len(name.strip()) > 2:
                return name.strip()

        # Fall back to detected name from file path
        if file_record.detected_employee_name and len(file_record.detected_employee_name) > 2:
            return file_record.detected_employee_name

        return None

    def _find_match(
        self, name: str
    ) -> Tuple[Optional[str], float, str, List[Dict[str, Any]]]:
        """Find best employee match using multiple strategies.

        Strategies (in order):
        1. Exact full-name match (case-insensitive)
        2. Email exact match
        3. Cleaned-name exact match
        4. Partial containment — extracted name contained in employee name or vice-versa
        5. Token-sort fuzzy match (RapidFuzz)

        Returns (employee_id, confidence, method, alternatives_list).
        """
        employees = self.db.query(Employee).filter(Employee.is_active == True).all()
        if not employees:
            return None, 0.0, "NO_EMPLOYEES", []

        name_lower = name.lower().strip()
        name_parts = set(name_lower.split())

        # 1+2+3 — exact matches
        for emp in employees:
            emp_lower = emp.full_name.lower().strip()
            if emp_lower == name_lower:
                return emp.id, 1.0, "EXACT", []
            if emp.email and emp.email.lower() == name_lower:
                return emp.id, 1.0, "EMAIL_EXACT", []
            cleaned_emp = _clean_name_for_matching(emp.full_name).lower()
            if cleaned_emp and cleaned_emp == name_lower:
                return emp.id, 1.0, "EXACT_CLEANED", []

        # 4 — partial containment (e.g. "Bharath" inside "Bharath Muddada")
        for emp in employees:
            emp_lower = emp.full_name.lower().strip()
            emp_parts = set(emp_lower.split())
            # All tokens of extracted name appear in employee name
            if name_parts and name_parts.issubset(emp_parts):
                conf = min(0.95, 0.70 + 0.05 * len(name_parts))
                return emp.id, conf, "PARTIAL_SUBSET", []
            # All tokens of employee name appear in extracted name
            if emp_parts and emp_parts.issubset(name_parts):
                conf = min(0.90, 0.65 + 0.05 * len(emp_parts))
                return emp.id, conf, "PARTIAL_SUPERSET", []

        # 5 — fuzzy match — collect all scores, return best with top-5 alternatives
        scores: List[Tuple[float, str, str]] = []
        for emp in employees:
            # Compare against full name and cleaned name, take best
            score_full = fuzz.token_sort_ratio(name_lower, emp.full_name.lower()) / 100.0
            cleaned_emp = _clean_name_for_matching(emp.full_name).lower()
            score_cleaned = fuzz.token_sort_ratio(name_lower, cleaned_emp) / 100.0 if cleaned_emp else 0.0
            # Also try partial ratio for cases like "Bharath M" vs "Bharath Muddada"
            score_partial = fuzz.partial_ratio(name_lower, emp.full_name.lower()) / 100.0
            score = max(score_full, score_cleaned, score_partial * 0.9)
            scores.append((score, emp.id, emp.full_name))

        scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_id, best_name = scores[0]

        alternatives = [
            {"employee_id": eid, "employee_name": ename, "confidence": round(sc, 4)}
            for sc, eid, ename in scores[1:6]
            if sc >= settings.FUZZY_REVIEW_THRESHOLD
        ]

        if best_score > 0:
            return best_id, best_score, "FUZZY", alternatives

        return None, 0.0, "NO_MATCH", []

    def _record_match(
        self,
        file_record: UploadedFile,
        detected_name: Optional[str],
        employee_id: Optional[str],
        method: str,
        confidence: float,
        status: str,
        alternatives: List[Dict],
    ) -> None:
        match = EmployeeFileMatch(
            id=gen_uuid(),
            file_id=file_record.id,
            detected_name=detected_name,
            matched_employee_id=employee_id,
            match_method=method,
            match_confidence=confidence,
            review_status=status,
            created_at=datetime.utcnow(),
        )
        self.db.add(match)

    def match_by_name(self, name: str, threshold: float = 80.0) -> Optional[str]:
        """Quick name-only match — returns employee_id or None. No DB side effects."""
        if not name:
            return None
        clean = _clean_name_for_matching(name)
        if not clean:
            return None
        employee_id, confidence, _, _ = self._find_match(clean)
        if employee_id and confidence >= threshold:
            return employee_id
        return None

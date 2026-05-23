"""
Employee matching service — Phase 5.
Exact match → fuzzy match → NEEDS_REVIEW.
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from rapidfuzz import fuzz, process as rfprocess

from app.core.config import settings
from app.db.models import Employee, UploadedFile, EmployeeFileMatch, RawExtraction, gen_uuid

logger = logging.getLogger(__name__)

EXACT_THRESHOLD = 1.0
FUZZY_AUTO_THRESHOLD = 0.85
FUZZY_REVIEW_THRESHOLD = 0.6


class EmployeeMatchService:
    def __init__(self, db: Session):
        self.db = db

    def match_file(self, file_record: UploadedFile) -> Optional[str]:
        """
        Attempt to match the file to an employee.
        Returns employee_id if matched, None if needs review or can't match.
        """
        candidate_name = self._get_candidate_name(file_record)
        if not candidate_name:
            self._record_match(file_record, None, None, "NO_NAME", 0.0, "NO_CANDIDATE")
            return None

        employee_id, confidence, method = self._find_match(candidate_name)

        if employee_id and confidence >= FUZZY_AUTO_THRESHOLD:
            file_record.matched_employee_id = employee_id
            file_record.match_confidence = confidence
            file_record.match_status = "AUTO_MATCHED"
        elif employee_id and confidence >= FUZZY_REVIEW_THRESHOLD:
            file_record.matched_employee_id = employee_id
            file_record.match_confidence = confidence
            file_record.match_status = "NEEDS_REVIEW"
        else:
            file_record.match_status = "NOT_MATCHED"
            file_record.match_confidence = confidence

        file_record.updated_at = datetime.utcnow()
        self._record_match(file_record, candidate_name, employee_id, method, confidence,
                           file_record.match_status)
        self.db.commit()
        return employee_id

    def _get_candidate_name(self, file_record: UploadedFile) -> Optional[str]:
        """Get best candidate name from file metadata or extracted data."""
        # From raw extraction JSON first (most reliable)
        raw = self.db.query(RawExtraction).filter(RawExtraction.file_id == file_record.id).first()
        if raw and raw.llm_json:
            name = raw.llm_json.get("employee_name")
            if name and len(name.strip()) > 2:
                return name.strip()

        # Fall back to detected name from file path
        if file_record.detected_employee_name and len(file_record.detected_employee_name) > 2:
            return file_record.detected_employee_name

        return None

    def _find_match(self, name: str) -> Tuple[Optional[str], float, str]:
        """Find best employee match. Returns (employee_id, confidence, method)."""
        employees = self.db.query(Employee).filter(Employee.is_active == True).all()
        if not employees:
            return None, 0.0, "NO_EMPLOYEES"

        # Exact match (case-insensitive)
        name_lower = name.lower().strip()
        for emp in employees:
            if emp.full_name.lower().strip() == name_lower:
                return emp.id, 1.0, "EXACT"
            if emp.email and emp.email.lower() == name_lower:
                return emp.id, 1.0, "EMAIL_EXACT"

        # Fuzzy match
        emp_names = [(emp.id, emp.full_name) for emp in employees]
        best_id, best_score = None, 0.0

        for emp_id, emp_name in emp_names:
            score = fuzz.token_sort_ratio(name_lower, emp_name.lower()) / 100.0
            if score > best_score:
                best_score = score
                best_id = emp_id

        if best_id:
            return best_id, best_score, "FUZZY"

        return None, 0.0, "NO_MATCH"

    def _record_match(
        self,
        file_record: UploadedFile,
        detected_name: Optional[str],
        employee_id: Optional[str],
        method: str,
        confidence: float,
        review_status: str,
    ) -> None:
        match = EmployeeFileMatch(
            id=gen_uuid(),
            file_id=file_record.id,
            detected_name=detected_name,
            matched_employee_id=employee_id,
            match_method=method,
            match_confidence=confidence,
            review_status=review_status,
        )
        self.db.add(match)

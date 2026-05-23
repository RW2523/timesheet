"""
File inventory service — Phase 1.
Safe ZIP extraction, recursive scanning, hash dedup, noise filtering.
"""
import os
import zipfile
import logging
import re
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UploadedFile, FileProcessingLog, RawExtraction, gen_uuid
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".docx", ".pdf", ".png", ".jpg", ".jpeg"}


class FileInventoryService:
    def __init__(self, db: Session):
        self.db = db
        self.storage = StorageService()

    def build_inventory(self, batch_id: str, zip_path: str) -> List[UploadedFile]:
        """Safely extract ZIP and create uploaded_files rows."""
        extract_dir = self.storage.batch_extract_dir(batch_id)
        self._safe_unzip(zip_path, extract_dir)
        return self._scan_and_register(batch_id, extract_dir)

    def _safe_unzip(self, zip_path: str, dest: str) -> None:
        """Extract ZIP with path traversal protection and size limit."""
        max_bytes = settings.MAX_EXTRACTED_MB * 1024 * 1024
        total_size = 0

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                # Prevent path traversal
                member_path = os.path.realpath(os.path.join(dest, member.filename))
                if not member_path.startswith(os.path.realpath(dest)):
                    logger.warning(f"Skipping unsafe path: {member.filename}")
                    continue

                total_size += member.file_size
                if total_size > max_bytes:
                    raise ValueError(
                        f"Extracted content exceeds {settings.MAX_EXTRACTED_MB} MB limit"
                    )

                zf.extract(member, dest)

        logger.info(f"Extracted ZIP to {dest} ({total_size / 1024 / 1024:.1f} MB)")

    def _scan_and_register(self, batch_id: str, root_dir: str) -> List[UploadedFile]:
        """Walk extracted directory, build UploadedFile rows."""
        noise_patterns = settings.noise_patterns
        seen_hashes: dict[str, str] = {}  # hash -> file_id
        records: List[UploadedFile] = []

        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Skip __MACOSX and hidden directories
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d.lower() not in ("__macosx",)
            ]
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_folder = os.path.relpath(dirpath, root_dir)
                if rel_folder == ".":
                    rel_folder = ""

                file_ext = os.path.splitext(fname)[1].lower()
                file_id = gen_uuid()

                # Noise detection
                is_noise = self._is_noise(fname, noise_patterns)
                if is_noise:
                    record = UploadedFile(
                        id=file_id,
                        batch_id=batch_id,
                        folder_path=rel_folder,
                        file_name=fname,
                        file_ext=file_ext,
                        file_size_bytes=os.path.getsize(full_path),
                        stored_file_path=full_path,
                        is_noise_file=True,
                        is_timesheet_candidate=False,
                        processing_status="IGNORED_NOISE",
                    )
                    self.db.add(record)
                    records.append(record)
                    continue

                # Hash + dedup
                try:
                    file_hash = StorageService.sha256(full_path)
                except Exception:
                    file_hash = None

                is_duplicate = False
                duplicate_of = None
                if file_hash and file_hash in seen_hashes:
                    is_duplicate = True
                    duplicate_of = seen_hashes[file_hash]
                elif file_hash:
                    seen_hashes[file_hash] = file_id

                # Detect names from path
                detected_employee, detected_vendor, detected_period = self._parse_path_metadata(
                    rel_folder, fname
                )

                # Determine if it looks like a timesheet
                is_candidate = file_ext in SUPPORTED_EXTENSIONS

                record = UploadedFile(
                    id=file_id,
                    batch_id=batch_id,
                    folder_path=rel_folder,
                    file_name=fname,
                    file_ext=file_ext,
                    file_size_bytes=StorageService.file_size(full_path),
                    file_hash=file_hash,
                    stored_file_path=full_path,
                    detected_employee_name=detected_employee,
                    detected_vendor_name=detected_vendor,
                    detected_period_text=detected_period,
                    is_duplicate=is_duplicate,
                    duplicate_of_file_id=duplicate_of,
                    is_noise_file=False,
                    is_timesheet_candidate=is_candidate,
                    processing_status="DUPLICATE" if is_duplicate else "DETECTED",
                )
                self.db.add(record)
                records.append(record)

        self.db.commit()
        logger.info(f"[{batch_id}] Registered {len(records)} files")
        return records

    @staticmethod
    def _is_noise(filename: str, noise_patterns: list[str]) -> bool:
        lower = filename.lower()
        return any(lower == p or lower.endswith(p) for p in noise_patterns)

    @staticmethod
    def _parse_path_metadata(folder_path: str, filename: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Heuristically extract employee name, vendor name, period from path."""
        parts = folder_path.replace("\\", "/").split("/") if folder_path else []
        name_stem = os.path.splitext(filename)[0]

        # Try to find period (month-year pattern)
        period_match = re.search(
            r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[_\-\s]?\d{4}|\d{4}[_\-]\d{2}",
            " ".join(parts + [name_stem]),
            re.IGNORECASE,
        )
        period = period_match.group(0) if period_match else None

        # Vendor is usually top-level folder
        vendor = parts[0] if parts and parts[0] else None

        # Employee name heuristic: last path segment or filename without period/ext
        employee_candidate = name_stem
        # Remove common suffixes
        for suffix in ["_timesheet", "_ts", "_hours", "_apr2026", "_may2026"]:
            employee_candidate = employee_candidate.replace(suffix, "").replace(suffix.upper(), "")
        employee_candidate = employee_candidate.strip("_- ").replace("_", " ").replace("-", " ").strip()
        employee = employee_candidate if employee_candidate else None

        return employee, vendor, period

    def mark_failed(self, file_id: str, error_msg: str) -> None:
        f = self.db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if f:
            f.processing_status = "FAILED"
            f.updated_at = datetime.utcnow()
            log = FileProcessingLog(
                id=gen_uuid(), file_id=file_id, stage="PROCESSING",
                status="FAILED", message=error_msg,
            )
            self.db.add(log)
            self.db.commit()

    def get_file(self, file_id: str) -> Optional[UploadedFile]:
        return self.db.query(UploadedFile).filter(UploadedFile.id == file_id).first()

    def get_raw_extractions(self, batch_id: str):
        from app.db.models import RawExtraction
        return (
            self.db.query(RawExtraction)
            .join(UploadedFile, RawExtraction.file_id == UploadedFile.id)
            .filter(UploadedFile.batch_id == batch_id)
            .all()
        )

    def get_unmatched_files(self, batch_id: str) -> List[UploadedFile]:
        return (
            self.db.query(UploadedFile)
            .filter(
                UploadedFile.batch_id == batch_id,
                UploadedFile.is_noise_file == False,
                UploadedFile.is_duplicate == False,
                UploadedFile.is_timesheet_candidate == True,
            )
            .all()
        )

    def get_raw_extraction_for_file(self, file_id: str) -> Optional[RawExtraction]:
        return self.db.query(RawExtraction).filter(RawExtraction.file_id == file_id).first()

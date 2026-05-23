"""Storage service — manages physical file paths on disk."""
import os
import hashlib
from app.core.config import settings


class StorageService:
    def __init__(self):
        self.root = settings.STORAGE_ROOT
        os.makedirs(os.path.join(self.root, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "extracted"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "raw_extractions"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "reports"), exist_ok=True)

    def batch_upload_dir(self, batch_id: str) -> str:
        return os.path.join(self.root, "uploads", batch_id)

    def batch_extract_dir(self, batch_id: str) -> str:
        path = os.path.join(self.root, "extracted", batch_id)
        os.makedirs(path, exist_ok=True)
        return path

    def reports_dir(self, batch_id: str) -> str:
        path = os.path.join(self.root, "reports", batch_id)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def sha256(file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def file_size(file_path: str) -> int:
        return os.path.getsize(file_path)

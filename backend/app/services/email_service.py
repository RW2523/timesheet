"""
Email ingestion service — Phase 10 (stub).
Routes email attachments through the same Common Processor as ZIP uploads.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmailService:
    """
    Stub for future email ingestion from timesheets@ajace.com.
    When implemented, this will:
      1. Connect to IMAP/Exchange inbox
      2. Download attachment files
      3. Save as batch_upload with source_type=EMAIL
      4. Enqueue process_batch task (same pipeline as ZIP)
    """

    def __init__(self, db=None):
        self.db = db

    def check_inbox(self) -> list:
        """Poll inbox for new timesheet emails. Returns list of batch IDs created."""
        logger.info("Email ingestion not yet implemented — Phase 10 stub")
        return []

    def process_email_attachment(
        self,
        sender: str,
        subject: str,
        attachment_path: str,
        attachment_name: str,
    ) -> Optional[str]:
        """
        Create a batch_upload record from an email attachment and enqueue processing.
        Uses source_type=EMAIL — routes through same pipeline as ZIP upload.
        """
        logger.info(f"Email attachment received from {sender}: {attachment_name}")
        # TODO Phase 10:
        # batch = BatchUpload(source_type="EMAIL", source_name=attachment_name, ...)
        # process_batch.delay(batch.id)
        return None

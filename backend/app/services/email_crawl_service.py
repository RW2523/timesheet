"""
Email crawl service.

Two-phase flow:
  Phase 1 (run_crawl_job):
    Search Gmail → classify each email (rule-based + LLM) → download attachments
    → status = AWAITING_APPROVAL
    The attachments are saved locally but NO batch is created yet.

  Phase 2 (approve_and_process):
    Called by the user after reviewing the found emails.
    Creates a BatchUpload from the approved messages' attachments
    → triggers the normal processing pipeline.
"""
import logging
import os
import shutil
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    BatchUpload, EmailAccount, EmailCrawlJob, EmailMessage,
    UploadedFile, gen_uuid,
)
from app.services.gmail_service import GmailService
from app.services.email_classifier_service import EmailClassifier
from app.services.employee_match_service import EmployeeMatchService

logger = logging.getLogger(__name__)

STORAGE_ROOT = getattr(settings, "STORAGE_ROOT", "/app/uploads")


class EmailCrawlService:
    def __init__(self, db: Session):
        self.db = db
        self.gmail = GmailService(db)
        self.classifier = EmailClassifier()
        self.em_svc = EmployeeMatchService(db)

    # ── Phase 1: Search + Classify + Download ─────────────────────────────────

    def run_crawl_job(self, job_id: str) -> EmailCrawlJob:
        """
        Phase 1 — Search Gmail, classify emails, download attachments.
        Stops at AWAITING_APPROVAL so the user can review before processing.
        """
        job = self.db.query(EmailCrawlJob).filter(EmailCrawlJob.id == job_id).first()
        if not job:
            raise ValueError(f"Crawl job not found: {job_id}")

        account = self.db.query(EmailAccount).filter(EmailAccount.id == job.account_id).first()
        if not account or not account.is_active:
            self._fail_job(job, "Account not found or inactive")
            return job

        job.status = "RUNNING"
        job.started_at = datetime.utcnow()
        self.db.commit()

        try:
            # Search Gmail
            messages = self.gmail.search_messages(
                account,
                date_start=str(job.period_start),
                date_end=str(job.period_end),
                extra_query=job.subject_filter or "",
            )
            job.emails_scanned = len(messages)
            self.db.commit()

            crawl_dir = os.path.join(STORAGE_ROOT, "email_crawls", job_id)
            os.makedirs(crawl_dir, exist_ok=True)

            timesheet_count = 0
            skipped_count   = 0

            for stub in messages:
                msg_id = stub["id"]

                # Skip already processed messages
                existing = (
                    self.db.query(EmailMessage)
                    .filter(EmailMessage.gmail_message_id == msg_id)
                    .first()
                )
                if existing and existing.processing_status in ("EXTRACTED", "SKIPPED"):
                    continue

                try:
                    detail = self.gmail.get_message_detail(account, msg_id)
                    is_ts, confidence, method, reason = self.classifier.classify(
                        subject=detail["subject"],
                        body_text=detail.get("body_text", ""),
                        attachments=detail["attachments"],
                        sender_email=detail["sender_email"],
                    )

                    em_rec = existing or EmailMessage(
                        id=gen_uuid(),
                        gmail_message_id=msg_id,
                        crawl_job_id=job_id,
                        account_id=account.id,
                    )
                    em_rec.subject                  = detail["subject"]
                    em_rec.sender_name              = detail["sender_name"]
                    em_rec.sender_email             = detail["sender_email"]
                    em_rec.received_at              = detail["received_at"]
                    em_rec.body_snippet             = detail["body_snippet"]
                    em_rec.is_timesheet             = is_ts
                    em_rec.classification_reason    = reason
                    em_rec.classification_method    = method
                    em_rec.classification_confidence = confidence
                    em_rec.has_attachments          = bool(detail["attachments"])
                    em_rec.attachments_metadata     = detail["attachments"]

                    if not existing:
                        self.db.add(em_rec)

                    if not is_ts:
                        em_rec.processing_status = "SKIPPED"
                        em_rec.skip_reason = f"Not a timesheet: {reason}"
                        skipped_count += 1
                        self.db.commit()
                        continue

                    # Download attachments — save locally, wait for user approval
                    timesheet_count += 1
                    sender_dir = os.path.join(crawl_dir, _safe_name(detail["sender_email"]))
                    saved_paths = []
                    updated_attachments = []

                    for att in detail["attachments"]:
                        if not _is_doc_attachment(att):
                            updated_attachments.append(att)
                            continue
                        try:
                            saved = self.gmail.download_attachment(
                                account,
                                msg_id,
                                att["attachment_id"],
                                att["name"],
                                sender_dir,
                            )
                            saved_paths.append(saved)
                            updated_attachments.append({**att, "saved_path": saved})
                        except Exception as e:
                            logger.warning(f"Attachment download failed [{att['name']}]: {e}")
                            updated_attachments.append(att)

                    # Store saved paths in metadata for Phase 2
                    em_rec.attachments_metadata = updated_attachments

                    if saved_paths:
                        # PENDING_APPROVAL: downloaded, waiting for user confirmation
                        em_rec.processing_status = "PENDING_APPROVAL"
                        job.attachments_saved = (job.attachments_saved or 0) + len(saved_paths)
                    else:
                        em_rec.processing_status = "SKIPPED"
                        em_rec.skip_reason = "No downloadable attachments"
                        skipped_count += 1
                        timesheet_count -= 1

                    self.db.commit()

                except Exception as e:
                    logger.error(f"Error processing message {msg_id}: {e}", exc_info=True)

            job.emails_timesheet = timesheet_count
            job.emails_skipped   = skipped_count
            # Phase 1 complete — wait for user approval
            job.status = "AWAITING_APPROVAL"
            account.last_crawled_at = datetime.utcnow()
            self.db.commit()

            logger.info(
                f"Crawl job {job_id} phase 1 done: "
                f"scanned={job.emails_scanned} timesheets={timesheet_count} "
                f"attachments={job.attachments_saved} → AWAITING_APPROVAL"
            )

        except Exception as e:
            logger.error(f"Crawl job {job_id} failed: {e}", exc_info=True)
            self._fail_job(job, str(e))

        return job

    # ── Phase 2: User approves → create batch → pipeline ──────────────────────

    def approve_and_process(
        self, job_id: str, approved_message_ids: List[str]
    ) -> BatchUpload:
        """
        Phase 2 — User has reviewed and selected which emails to process.
        Creates a batch from the approved messages' attachments and starts processing.
        """
        job = self.db.query(EmailCrawlJob).filter(EmailCrawlJob.id == job_id).first()
        if not job:
            raise ValueError(f"Crawl job not found: {job_id}")

        account = self.db.query(EmailAccount).filter(EmailAccount.id == job.account_id).first()

        # Collect approved messages
        messages = (
            self.db.query(EmailMessage)
            .filter(
                EmailMessage.crawl_job_id == job_id,
                EmailMessage.id.in_(approved_message_ids),
                EmailMessage.processing_status == "PENDING_APPROVAL",
            )
            .all()
        )

        if not messages:
            raise ValueError("No approved messages found to process")

        # Build attachment list from approved messages
        attachment_files: list[dict] = []
        for msg in messages:
            for att in (msg.attachments_metadata or []):
                saved_path = att.get("saved_path")
                if saved_path and os.path.exists(saved_path) and _is_doc_attachment(att):
                    attachment_files.append({
                        "path":         saved_path,
                        "filename":     att["name"],
                        "sender_name":  msg.sender_name or "",
                        "sender_email": msg.sender_email or "",
                        "message_id":   msg.id,
                    })

        if not attachment_files:
            raise ValueError("No attachment files found for approved messages")

        batch = self._create_batch_from_attachments(attachment_files, job, account)

        # Link approved messages to the batch
        for msg in messages:
            msg.processing_status = "EXTRACTED"
            msg.batch_id = batch.id

        # Mark any non-approved PENDING_APPROVAL messages as SKIPPED
        self.db.query(EmailMessage).filter(
            EmailMessage.crawl_job_id == job_id,
            EmailMessage.processing_status == "PENDING_APPROVAL",
            ~EmailMessage.id.in_(approved_message_ids),
        ).update(
            {"processing_status": "SKIPPED", "skip_reason": "Not selected by user"},
            synchronize_session=False,
        )

        job.batch_id = batch.id
        job.status   = "COMPLETED"
        job.completed_at = datetime.utcnow()
        self.db.commit()

        logger.info(
            f"Crawl job {job_id} approved: {len(messages)} messages → "
            f"batch {batch.id} ({len(attachment_files)} files)"
        )
        return batch

    # ── Batch creation ─────────────────────────────────────────────────────────

    def _create_batch_from_attachments(
        self,
        attachment_files: list[dict],
        job: EmailCrawlJob,
        account: EmailAccount,
    ) -> BatchUpload:
        batch_id  = gen_uuid()
        batch_dir = os.path.join(STORAGE_ROOT, "uploads", batch_id)
        os.makedirs(batch_dir, exist_ok=True)

        label = (
            f"Email crawl {str(job.period_start)} – {str(job.period_end)} "
            f"({account.email_address})"
        )
        batch = BatchUpload(
            id=batch_id,
            source_type="EMAIL",
            source_name=label,
            status="UPLOADED",
            filter_period_start=str(job.period_start),
            filter_period_end=str(job.period_end),
            original_file_path=None,
            current_stage="Queued…",
            summary_json={
                "crawl_job_id": job.id,
                "account_email": account.email_address if account else "",
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(batch)

        file_count = 0
        for att in attachment_files:
            src  = att["path"]
            name = os.path.basename(src)
            dest = os.path.join(batch_dir, name)
            try:
                shutil.copy2(src, dest)
            except Exception as e:
                logger.warning(f"Could not copy {src} → {dest}: {e}")
                continue

            employee_id = self._match_employee_from_sender(
                att["sender_name"], att["sender_email"]
            )

            uf = UploadedFile(
                id=gen_uuid(),
                batch_id=batch_id,
                file_name=name,
                stored_file_path=dest,
                file_ext=os.path.splitext(name)[1].lstrip(".").lower(),
                file_size_bytes=os.path.getsize(dest),
                processing_status="DETECTED",
                match_status="NOT_MATCHED" if not employee_id else "AUTO_MATCHED",
                detected_employee_name=att["sender_name"] or None,
                matched_employee_id=employee_id,
                alerts_json={"source_email": att["sender_email"]} if att.get("sender_email") else None,
                created_at=datetime.utcnow(),
            )
            self.db.add(uf)
            file_count += 1

        batch.total_files = file_count
        self.db.commit()
        self.db.refresh(batch)
        logger.info(f"Created email batch {batch_id} with {file_count} files")

        if file_count > 0:
            self._trigger_batch_processing(batch_id)

        return batch

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _match_employee_from_sender(
        self, sender_name: str, sender_email: str
    ) -> Optional[str]:
        from app.db.models import Employee
        if sender_email:
            emp = (
                self.db.query(Employee)
                .filter(Employee.email == sender_email.lower())
                .first()
            )
            if emp:
                return emp.id
        if sender_name:
            try:
                return self.em_svc.match_by_name(sender_name, threshold=80)
            except Exception:
                pass
        return None

    def _trigger_batch_processing(self, batch_id: str):
        try:
            from app.workers.tasks import process_batch
            process_batch.delay(batch_id)
        except Exception as e:
            logger.error(f"Failed to trigger processing for batch {batch_id}: {e}")

    def _fail_job(self, job: EmailCrawlJob, error: str):
        job.status = "FAILED"
        job.error_message = error
        job.completed_at = datetime.utcnow()
        self.db.commit()


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in (s or ""))[:80]


def _is_doc_attachment(att: dict) -> bool:
    exts = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff"}
    return any((att.get("name") or "").lower().endswith(e) for e in exts)

"""
Email Integration API routes.

Endpoints:
  GET  /email/accounts                        - list connected email accounts
  POST /email/accounts/gmail/auth-url         - get Google OAuth URL to open in browser
  POST /email/accounts/gmail/connect          - exchange OAuth code → save tokens
  DELETE /email/accounts/{id}                 - disconnect / revoke account
  GET  /email/crawl-jobs                      - list crawl jobs (with optional account filter)
  POST /email/crawl-jobs                      - create + enqueue a crawl job
  GET  /email/crawl-jobs/{id}                 - get crawl job detail (+ messages summary)
  GET  /email/crawl-jobs/{id}/messages        - list email messages for a job
  POST /email/crawl-jobs/{id}/retry           - retry a failed job
"""
import logging
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import EmailAccount, EmailCrawlJob, EmailMessage, gen_uuid
from app.services.gmail_service import GmailService
from app.core.config import settings

router = APIRouter(prefix="/email")
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class GmailConnectRequest(BaseModel):
    code: str
    label: str = "Gmail"


class CrawlJobRequest(BaseModel):
    account_id: str
    period_start: date
    period_end: date
    subject_filter: Optional[str] = None


class AccountOut(BaseModel):
    id: str
    label: str
    email_address: str
    provider: str
    is_active: bool
    last_crawled_at: Optional[datetime] = None
    created_at: datetime


class CrawlJobOut(BaseModel):
    id: str
    account_id: str
    account_email: Optional[str] = None
    period_start: date
    period_end: date
    subject_filter: Optional[str] = None
    status: str   # PENDING RUNNING AWAITING_APPROVAL COMPLETED FAILED
    emails_scanned: int
    emails_timesheet: int
    emails_skipped: int
    attachments_saved: int
    batch_id: Optional[str] = None
    triggered_by: str
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    pending_approval_count: int = 0   # emails waiting for user confirmation


class EmailMessageOut(BaseModel):
    id: str
    gmail_message_id: str
    subject: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    received_at: Optional[datetime] = None
    body_snippet: Optional[str] = None
    is_timesheet: Optional[bool] = None
    classification_reason: Optional[str] = None
    classification_method: Optional[str] = None
    classification_confidence: Optional[float] = None
    has_attachments: bool
    attachments_metadata: Optional[list] = None
    processing_status: str
    batch_id: Optional[str] = None
    skip_reason: Optional[str] = None
    created_at: datetime


# ── Helper ────────────────────────────────────────────────────────────────────

def _account_out(acc: EmailAccount) -> AccountOut:
    return AccountOut(
        id=acc.id,
        label=acc.label or acc.email_address,
        email_address=acc.email_address,
        provider=acc.provider,
        is_active=acc.is_active,
        last_crawled_at=acc.last_crawled_at,
        created_at=acc.created_at,
    )


def _job_out(job: EmailCrawlJob, db: Session) -> CrawlJobOut:
    account = db.query(EmailAccount).filter(EmailAccount.id == job.account_id).first()
    pending = (
        db.query(EmailMessage)
        .filter(
            EmailMessage.crawl_job_id == job.id,
            EmailMessage.processing_status == "PENDING_APPROVAL",
        )
        .count()
    )
    return CrawlJobOut(
        id=job.id,
        account_id=job.account_id,
        account_email=account.email_address if account else None,
        period_start=job.period_start,
        period_end=job.period_end,
        subject_filter=job.subject_filter,
        status=job.status,
        emails_scanned=job.emails_scanned or 0,
        emails_timesheet=job.emails_timesheet or 0,
        emails_skipped=job.emails_skipped or 0,
        attachments_saved=job.attachments_saved or 0,
        batch_id=job.batch_id,
        triggered_by=job.triggered_by or "MANUAL",
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        pending_approval_count=pending,
    )


# ── Accounts ──────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=List[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(EmailAccount).order_by(EmailAccount.created_at.desc()).all()
    return [_account_out(a) for a in accounts]


@router.get("/accounts/gmail/auth-url")
def gmail_auth_url(label: str = "Gmail", db: Session = Depends(get_db)):
    """Return the Google OAuth2 authorization URL."""
    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        raise HTTPException(
            status_code=501,
            detail=(
                "Gmail OAuth is not configured. "
                "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in the .env file. "
                "See: https://console.cloud.google.com/apis/credentials"
            ),
        )
    svc = GmailService(db)
    # Pass label as state so the callback page knows what label to use
    url = svc.get_auth_url(state=label)
    return {"auth_url": url, "redirect_uri": settings.GMAIL_REDIRECT_URI}


@router.post("/accounts/gmail/connect", response_model=AccountOut)
def gmail_connect(req: GmailConnectRequest, db: Session = Depends(get_db)):
    """Exchange OAuth authorization code for tokens and store the account."""
    svc = GmailService(db)
    try:
        account = svc.exchange_code(code=req.code, label=req.label)
    except Exception as e:
        logger.error(f"Gmail connect error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    return _account_out(account)


@router.delete("/accounts/{account_id}")
def disconnect_account(account_id: str, db: Session = Depends(get_db)):
    """Revoke OAuth tokens and mark account as inactive."""
    svc = GmailService(db)
    svc.disconnect_account(account_id)
    return {"message": "Account disconnected"}


# ── Crawl Jobs ────────────────────────────────────────────────────────────────

@router.get("/crawl-jobs", response_model=List[CrawlJobOut])
def list_crawl_jobs(
    account_id: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(EmailCrawlJob).order_by(EmailCrawlJob.created_at.desc())
    if account_id:
        q = q.filter(EmailCrawlJob.account_id == account_id)
    return [_job_out(j, db) for j in q.limit(limit).all()]


@router.post("/crawl-jobs", response_model=CrawlJobOut, status_code=202)
def create_crawl_job(req: CrawlJobRequest, db: Session = Depends(get_db)):
    """Create a crawl job and dispatch it to the Celery worker."""
    # Validate account exists and is active
    account = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == req.account_id, EmailAccount.is_active == True)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found or inactive")

    if req.period_start > req.period_end:
        raise HTTPException(status_code=422, detail="period_start must be before period_end")

    # Create job record
    job = EmailCrawlJob(
        id=gen_uuid(),
        account_id=req.account_id,
        period_start=req.period_start,
        period_end=req.period_end,
        subject_filter=req.subject_filter,
        status="PENDING",
        triggered_by="MANUAL",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch Celery task
    try:
        from app.workers.tasks import crawl_email_job
        crawl_email_job.delay(job.id)
        logger.info(f"Crawl job {job.id} dispatched to worker")
    except Exception as e:
        logger.error(f"Failed to dispatch crawl job: {e}")
        job.status = "FAILED"
        job.error_message = f"Worker dispatch failed: {e}"
        db.commit()

    return _job_out(job, db)


@router.get("/crawl-jobs/{job_id}", response_model=CrawlJobOut)
def get_crawl_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(EmailCrawlJob).filter(EmailCrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return _job_out(job, db)


@router.get("/crawl-jobs/{job_id}/messages", response_model=List[EmailMessageOut])
def list_job_messages(
    job_id: str,
    is_timesheet: Optional[bool] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(EmailMessage).filter(EmailMessage.crawl_job_id == job_id)
    if is_timesheet is not None:
        q = q.filter(EmailMessage.is_timesheet == is_timesheet)
    if status:
        q = q.filter(EmailMessage.processing_status == status)
    messages = q.order_by(EmailMessage.received_at.desc()).limit(limit).all()
    return [
        EmailMessageOut(
            id=m.id,
            gmail_message_id=m.gmail_message_id,
            subject=m.subject,
            sender_name=m.sender_name,
            sender_email=m.sender_email,
            received_at=m.received_at,
            body_snippet=m.body_snippet,
            is_timesheet=m.is_timesheet,
            classification_reason=m.classification_reason,
            classification_method=m.classification_method,
            classification_confidence=float(m.classification_confidence) if m.classification_confidence is not None else None,
            has_attachments=bool(m.has_attachments),
            attachments_metadata=m.attachments_metadata,
            processing_status=m.processing_status,
            batch_id=m.batch_id,
            skip_reason=m.skip_reason,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/crawl-jobs/{job_id}/retry", response_model=CrawlJobOut, status_code=202)
def retry_crawl_job(job_id: str, db: Session = Depends(get_db)):
    """Re-enqueue a failed crawl job."""
    job = db.query(EmailCrawlJob).filter(EmailCrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    if job.status not in ("FAILED", "PENDING"):
        raise HTTPException(status_code=409, detail=f"Job is {job.status}, cannot retry")
    job.status = "PENDING"
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    db.commit()
    try:
        from app.workers.tasks import crawl_email_job
        crawl_email_job.delay(job.id)
    except Exception as e:
        logger.error(f"Retry dispatch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Worker dispatch failed: {e}")
    return _job_out(job, db)


class ApproveRequest(BaseModel):
    message_ids: List[str]   # IDs of EmailMessage rows the user approved


@router.post("/crawl-jobs/{job_id}/approve", status_code=202)
def approve_crawl_job(job_id: str, req: ApproveRequest, db: Session = Depends(get_db)):
    """
    Phase 2 — User reviewed the found emails and confirmed which ones to process.
    Creates a batch from the approved messages and starts the pipeline.
    """
    job = db.query(EmailCrawlJob).filter(EmailCrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    if job.status != "AWAITING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Job status is '{job.status}' — can only approve jobs in AWAITING_APPROVAL state",
        )
    if not req.message_ids:
        raise HTTPException(status_code=422, detail="No message IDs provided")

    from app.services.email_crawl_service import EmailCrawlService
    svc = EmailCrawlService(db)
    try:
        batch = svc.approve_and_process(job_id, req.message_ids)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"approve_and_process failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": f"Processing started for {len(req.message_ids)} email(s)",
        "batch_id": batch.id,
        "total_files": batch.total_files,
    }

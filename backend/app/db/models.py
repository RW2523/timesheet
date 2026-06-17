"""
SQLAlchemy ORM models for all 22 database tables.
UUID primary keys, JSONB columns, full referential integrity.
"""
import uuid
from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, Any

from sqlalchemy import (
    Column, String, Boolean, Integer, BigInteger, Numeric, Date, Time,
    DateTime, Text, ForeignKey, Index, CheckConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Master Tables ──────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(Text, unique=True, nullable=False)
    full_name = Column(Text, nullable=False)
    role = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('HR', 'PAYROLL', 'ADMIN', 'MANAGER')", name="ck_users_role"),
    )


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(Text, unique=True, nullable=False)
    overtime_enabled = Column(Boolean, default=False)
    regular_daily_limit = Column(Numeric(5, 2), default=Decimal("8.0"))
    regular_weekly_limit = Column(Numeric(6, 2), default=Decimal("40.0"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employees = relationship("Employee", back_populates="vendor")


class ClientManager(Base):
    __tablename__ = "client_managers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    full_name = Column(Text, nullable=False)
    email = Column(Text, unique=True)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Employee(Base):
    __tablename__ = "employees"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    employee_code = Column(Text, unique=True)
    full_name = Column(Text, nullable=False)
    email = Column(Text, unique=True)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    client_manager_id = Column(UUID(as_uuid=False), ForeignKey("client_managers.id"))
    employee_type = Column(String(30))
    is_active = Column(Boolean, default=True)
    last_submission_month = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="employees")
    rates = relationship("EmployeeRate", back_populates="employee")

    __table_args__ = (
        CheckConstraint(
            "employee_type IN ('AJACE_INTERNAL', 'CONTRACTOR', 'CLIENT_VENDOR')",
            name="ck_employees_type",
        ),
    )


class EmployeeRate(Base):
    __tablename__ = "employee_rates"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"), nullable=False)
    regular_rate = Column(Numeric(10, 4), nullable=False)
    overtime_rate = Column(Numeric(10, 4))
    currency = Column(String(3), default="USD")
    effective_start_date = Column(Date, nullable=False)
    effective_end_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", back_populates="rates")


class HolidayCalendar(Base):
    __tablename__ = "holiday_calendars"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    applies_to_employee_type = Column(Text)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    dates = relationship("HolidayDate", back_populates="calendar")


class HolidayDate(Base):
    __tablename__ = "holiday_dates"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    calendar_id = Column(UUID(as_uuid=False), ForeignKey("holiday_calendars.id"), nullable=False)
    holiday_date = Column(Date, nullable=False)
    holiday_name = Column(Text, nullable=False)
    paid_hours = Column(Numeric(4, 2), default=Decimal("8.0"))
    created_at = Column(DateTime, default=datetime.utcnow)

    calendar = relationship("HolidayCalendar", back_populates="dates")


class PayrollPeriod(Base):
    __tablename__ = "payroll_periods"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    period_key = Column(Text, unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    cutoff_date = Column(Date, nullable=False)
    payroll_run_date = Column(Date)
    status = Column(String(20), default="OPEN")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Batch / File Tables ────────────────────────────────────────────────────────

class BatchUpload(Base):
    __tablename__ = "batch_uploads"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    source_type = Column(String(20), nullable=False)
    source_name = Column(Text, nullable=False)
    payroll_period_id = Column(UUID(as_uuid=False), ForeignKey("payroll_periods.id"))
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    original_file_path = Column(Text)
    status = Column(String(30), nullable=False, default="UPLOADED")
    total_files = Column(Integer, default=0)
    ignored_files = Column(Integer, default=0)
    duplicate_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    failed_files = Column(Integer, default=0)
    review_required_files = Column(Integer, default=0)
    payroll_ready_count = Column(Integer, default=0)
    summary_json = Column(JSONB)
    filter_period_start = Column(Text)   # ISO date — only keep entries on/after this date
    filter_period_end = Column(Text)     # ISO date — only keep entries on/before this date
    current_file = Column(Text)          # file being processed right now
    current_stage = Column(Text)         # e.g. "Parsing 3/58", "Normalizing", "Matching"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('ZIP_UPLOAD', 'EMAIL')",
            name="ck_batch_uploads_source_type",
        ),
    )

    files = relationship("UploadedFile", back_populates="batch")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batch_uploads.id"), nullable=False)
    folder_path = Column(Text)
    file_name = Column(Text, nullable=False)
    file_ext = Column(String(20))
    file_size_bytes = Column(BigInteger)
    file_hash = Column(Text)
    stored_file_path = Column(Text)
    detected_employee_name = Column(Text)
    detected_vendor_name = Column(Text)
    detected_period_text = Column(Text)
    matched_employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    match_confidence = Column(Numeric(5, 4))
    match_status = Column(String(20), default="NOT_MATCHED")
    parser_name = Column(Text)
    ocr_required = Column(Boolean, default=False)
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"))
    is_noise_file = Column(Boolean, default=False)
    is_timesheet_candidate = Column(Boolean, default=True)
    processing_status = Column(String(30), default="DETECTED")
    alerts_json = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = relationship("BatchUpload", back_populates="files")
    processing_logs = relationship("FileProcessingLog", back_populates="file")
    raw_extractions = relationship("RawExtraction", back_populates="file")

    __table_args__ = (
        Index("idx_uploaded_files_batch_id", "batch_id"),
        Index("idx_uploaded_files_hash", "file_hash"),
    )


class FileProcessingLog(Base):
    __tablename__ = "file_processing_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"), nullable=False)
    stage = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    message = Column(Text)
    log_metadata = Column("metadata", JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("UploadedFile", back_populates="processing_logs")


# ── Extraction Tables ──────────────────────────────────────────────────────────

class RawExtraction(Base):
    __tablename__ = "raw_extractions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"), nullable=False)
    extraction_method = Column(Text, nullable=False)
    raw_text = Column(Text)
    raw_tables = Column(JSONB)
    llm_json = Column(JSONB)
    confidence = Column(Numeric(5, 4))
    extraction_warnings = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("UploadedFile", back_populates="raw_extractions")


class EmployeeFileMatch(Base):
    __tablename__ = "employee_file_matches"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"), nullable=False)
    detected_name = Column(Text)
    matched_employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    match_method = Column(Text)
    match_confidence = Column(Numeric(5, 4))
    review_status = Column(String(20), default="AUTO")
    reviewed_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Timesheet Tables ───────────────────────────────────────────────────────────

class TimesheetSubmission(Base):
    __tablename__ = "timesheet_submissions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batch_uploads.id"))
    file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"))
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    # Name extracted from the document, kept even when no employee match exists
    # (matching is optional metadata, not a gate on extraction).
    detected_employee_name = Column(Text)
    payroll_period_id = Column(UUID(as_uuid=False), ForeignKey("payroll_periods.id"))
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    source_type = Column(Text, nullable=False)
    submission_date = Column(DateTime)
    timesheet_start_date = Column(Date)
    timesheet_end_date = Column(Date)
    approval_status = Column(String(20), default="PENDING")
    approved_by_name = Column(Text)
    approved_by_email = Column(Text)
    approved_at = Column(DateTime)
    validation_status = Column(String(20), default="PENDING")
    payroll_status = Column(String(20), default="NOT_READY")
    is_late = Column(Boolean, default=False)
    payable_period_id = Column(UUID(as_uuid=False), ForeignKey("payroll_periods.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    entries = relationship("TimesheetEntry", back_populates="submission")
    validation_errors = relationship("ValidationError", back_populates="submission")

    __table_args__ = (
        Index(
            "idx_timesheet_submissions_employee_period",
            "employee_id",
            "payroll_period_id",
        ),
    )


class TimesheetEntry(Base):
    __tablename__ = "timesheet_entries"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    submission_id = Column(UUID(as_uuid=False), ForeignKey("timesheet_submissions.id"), nullable=False)
    # Nullable: a timesheet is fully extracted even when the employee is unmatched.
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    work_date = Column(Date, nullable=False)
    day_of_week = Column(String(10))
    in_time = Column(Time)
    out_time = Column(Time)
    break_minutes = Column(Integer, default=0)
    entered_hours = Column(Numeric(5, 2))
    calculated_hours = Column(Numeric(5, 2))
    regular_hours = Column(Numeric(5, 2), default=Decimal("0"))
    overtime_hours = Column(Numeric(5, 2), default=Decimal("0"))
    entry_type = Column(String(20), default="WORK")
    leave_type = Column(String(30))
    is_holiday = Column(Boolean, default=False)
    holiday_name = Column(Text)
    source_file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"))
    row_source = Column(JSONB)
    validation_status = Column(String(20), default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submission = relationship("TimesheetSubmission", back_populates="entries")

    __table_args__ = (
        Index("idx_timesheet_entries_employee_date", "employee_id", "work_date"),
    )


# ── Validation / Approval Tables ───────────────────────────────────────────────

class ValidationError(Base):
    __tablename__ = "validation_errors"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batch_uploads.id"))
    file_id = Column(UUID(as_uuid=False), ForeignKey("uploaded_files.id"))
    submission_id = Column(UUID(as_uuid=False), ForeignKey("timesheet_submissions.id"))
    entry_id = Column(UUID(as_uuid=False), ForeignKey("timesheet_entries.id"))
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    rule_code = Column(Text, nullable=False)
    severity = Column(String(10), nullable=False)
    message = Column(Text, nullable=False)
    expected_value = Column(Text)
    actual_value = Column(Text)
    action_required = Column(Text)
    assigned_to_role = Column(Text)
    status = Column(String(20), default="OPEN")
    resolved_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("TimesheetSubmission", back_populates="validation_errors")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR', 'BLOCKER')",
            name="ck_validation_errors_severity",
        ),
        Index("idx_validation_errors_status", "status"),
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    submission_id = Column(UUID(as_uuid=False), ForeignKey("timesheet_submissions.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"), nullable=False)
    approver_name = Column(Text)
    approver_email = Column(Text)
    approval_status = Column(String(20), nullable=False)
    approval_source = Column(Text)
    approval_date = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_approval_records_status",
        ),
    )


# ── Payroll Tables ─────────────────────────────────────────────────────────────

class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    payroll_period_id = Column(UUID(as_uuid=False), ForeignKey("payroll_periods.id"), nullable=False)
    run_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    run_status = Column(String(20), default="DRAFT")
    total_employees = Column(Integer, default=0)
    payroll_ready_employees = Column(Integer, default=0)
    blocked_employees = Column(Integer, default=0)
    total_regular_hours = Column(Numeric(10, 2), default=Decimal("0"))
    total_overtime_hours = Column(Numeric(10, 2), default=Decimal("0"))
    total_regular_pay = Column(Numeric(15, 4), default=Decimal("0"))
    total_overtime_pay = Column(Numeric(15, 4), default=Decimal("0"))
    total_pay = Column(Numeric(15, 4), default=Decimal("0"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    results = relationship("PayrollResult", back_populates="payroll_run")


class PayrollResult(Base):
    __tablename__ = "payroll_results"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    payroll_run_id = Column(UUID(as_uuid=False), ForeignKey("payroll_runs.id"), nullable=False)
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=False), ForeignKey("vendors.id"))
    regular_hours = Column(Numeric(10, 2), default=Decimal("0"))
    overtime_hours = Column(Numeric(10, 2), default=Decimal("0"))
    leave_days = Column(Numeric(6, 2), default=Decimal("0"))
    holiday_hours = Column(Numeric(6, 2), default=Decimal("0"))
    regular_rate = Column(Numeric(10, 4))
    overtime_rate = Column(Numeric(10, 4))
    regular_pay = Column(Numeric(15, 4), default=Decimal("0"))
    overtime_pay = Column(Numeric(15, 4), default=Decimal("0"))
    total_pay = Column(Numeric(15, 4), default=Decimal("0"))
    payroll_status = Column(String(20), default="READY")
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    payroll_run = relationship("PayrollRun", back_populates="results")

    __table_args__ = (Index("idx_payroll_results_run", "payroll_run_id"),)


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batch_uploads.id"))
    payroll_run_id = Column(UUID(as_uuid=False), ForeignKey("payroll_runs.id"))
    report_type = Column(Text, nullable=False)
    file_name = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    generated_by = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Audit / Notification Tables ────────────────────────────────────────────────

class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    employee_id = Column(UUID(as_uuid=False), ForeignKey("employees.id"))
    recipient_email = Column(Text, nullable=False)
    notification_type = Column(Text, nullable=False)
    subject = Column(Text)
    body = Column(Text)
    status = Column(String(20), default="PENDING")
    sent_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    actor_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"))
    entity_type = Column(Text, nullable=False)
    entity_id = Column(UUID(as_uuid=False))
    action = Column(Text, nullable=False)
    before_json = Column(JSONB)
    after_json = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Email Integration Tables ───────────────────────────────────────────────────

class EmailAccount(Base):
    """A connected Gmail account (one per HR user / department)."""
    __tablename__ = "email_accounts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    label = Column(Text, nullable=False)           # user-friendly name e.g. "HR Gmail"
    email_address = Column(Text, nullable=False, unique=True)
    provider = Column(String(20), default="gmail") # future: outlook, etc.

    # OAuth tokens — stored as text; encrypt at rest via env-level disk encryption
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expiry = Column(DateTime)

    is_active = Column(Boolean, default=True)
    last_crawled_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    crawl_jobs = relationship("EmailCrawlJob", back_populates="account")


class EmailCrawlJob(Base):
    """A single crawl run — scans a date range and collects timesheet emails."""
    __tablename__ = "email_crawl_jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    account_id = Column(UUID(as_uuid=False), ForeignKey("email_accounts.id"), nullable=False)

    # Crawl parameters
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    subject_filter = Column(Text)   # optional extra Gmail search query

    # Status tracking
    status = Column(String(20), default="PENDING")  # PENDING RUNNING COMPLETED FAILED
    emails_scanned = Column(Integer, default=0)
    emails_timesheet = Column(Integer, default=0)   # classified as timesheet submission
    emails_skipped = Column(Integer, default=0)     # not timesheet
    attachments_saved = Column(Integer, default=0)

    # Output
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batch_uploads.id"))
    triggered_by = Column(String(20), default="MANUAL")  # MANUAL / SCHEDULE
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    account = relationship("EmailAccount", back_populates="crawl_jobs")
    messages = relationship("EmailMessage", back_populates="crawl_job")

    __table_args__ = (Index("idx_email_crawl_account", "account_id"),)


class EmailMessage(Base):
    """A single email processed during a crawl job."""
    __tablename__ = "email_messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    crawl_job_id = Column(UUID(as_uuid=False), ForeignKey("email_crawl_jobs.id"), nullable=False)
    account_id = Column(UUID(as_uuid=False), ForeignKey("email_accounts.id"), nullable=False)

    # Gmail identity — used to deduplicate across crawls
    gmail_message_id = Column(Text, nullable=False, unique=True)

    # Email header data
    subject = Column(Text)
    sender_name = Column(Text)
    sender_email = Column(Text)
    received_at = Column(DateTime)
    body_snippet = Column(Text)  # first 500 chars of body

    # Classification result
    is_timesheet = Column(Boolean)
    classification_reason = Column(Text)
    classification_method = Column(String(20))  # RULE_BASED / LLM / MANUAL
    classification_confidence = Column(Numeric(4, 3))

    # Attachments
    has_attachments = Column(Boolean, default=False)
    attachments_metadata = Column(JSONB)  # [{name, size_bytes, mime, saved_path}]

    # Processing outcome
    processing_status = Column(String(20), default="PENDING")  # PENDING EXTRACTED SKIPPED FAILED
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batch_uploads.id"))
    skip_reason = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    crawl_job = relationship("EmailCrawlJob", back_populates="messages")

    __table_args__ = (
        Index("idx_email_messages_sender", "sender_email"),
        Index("idx_email_messages_job", "crawl_job_id"),
    )

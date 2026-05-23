"""Initial schema — all 22 tables.

Revision ID: 001
Revises:
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Master tables ──────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('HR','PAYROLL','ADMIN','MANAGER')", name="ck_users_role"),
    )

    op.create_table(
        "vendors",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("overtime_enabled", sa.Boolean, default=False),
        sa.Column("regular_daily_limit", sa.Numeric(5, 2), default=8),
        sa.Column("regular_weekly_limit", sa.Numeric(6, 2), default=40),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "client_managers",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, unique=True),
        sa.Column("vendor_id", UUID(as_uuid=False), sa.ForeignKey("vendors.id")),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "employees",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("employee_code", sa.Text, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, unique=True),
        sa.Column("vendor_id", UUID(as_uuid=False), sa.ForeignKey("vendors.id")),
        sa.Column("client_manager_id", UUID(as_uuid=False), sa.ForeignKey("client_managers.id")),
        sa.Column("employee_type", sa.String(30)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("last_submission_month", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "employee_type IN ('AJACE_INTERNAL','CONTRACTOR','CLIENT_VENDOR')",
            name="ck_employees_type",
        ),
    )

    op.create_table(
        "employee_rates",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("regular_rate", sa.Numeric(10, 4), nullable=False),
        sa.Column("overtime_rate", sa.Numeric(10, 4)),
        sa.Column("currency", sa.String(3), default="USD"),
        sa.Column("effective_start_date", sa.Date, nullable=False),
        sa.Column("effective_end_date", sa.Date),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "holiday_calendars",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("applies_to_employee_type", sa.Text),
        sa.Column("vendor_id", UUID(as_uuid=False), sa.ForeignKey("vendors.id")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "holiday_dates",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("calendar_id", UUID(as_uuid=False), sa.ForeignKey("holiday_calendars.id"), nullable=False),
        sa.Column("holiday_date", sa.Date, nullable=False),
        sa.Column("holiday_name", sa.Text, nullable=False),
        sa.Column("paid_hours", sa.Numeric(4, 2), default=8),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "payroll_periods",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("period_key", sa.Text, unique=True, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("cutoff_date", sa.Date, nullable=False),
        sa.Column("payroll_run_date", sa.Date),
        sa.Column("status", sa.String(20), default="OPEN"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Batch / File tables ────────────────────────────────────────────────────
    op.create_table(
        "batch_uploads",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("payroll_period_id", UUID(as_uuid=False), sa.ForeignKey("payroll_periods.id")),
        sa.Column("uploaded_by", UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("original_file_path", sa.Text),
        sa.Column("status", sa.String(30), nullable=False, default="UPLOADED"),
        sa.Column("total_files", sa.Integer, default=0),
        sa.Column("ignored_files", sa.Integer, default=0),
        sa.Column("duplicate_files", sa.Integer, default=0),
        sa.Column("processed_files", sa.Integer, default=0),
        sa.Column("failed_files", sa.Integer, default=0),
        sa.Column("review_required_files", sa.Integer, default=0),
        sa.Column("payroll_ready_count", sa.Integer, default=0),
        sa.Column("summary_json", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "source_type IN ('ZIP_UPLOAD','EMAIL')",
            name="ck_batch_uploads_source_type",
        ),
    )

    op.create_table(
        "uploaded_files",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("batch_uploads.id"), nullable=False),
        sa.Column("folder_path", sa.Text),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("file_ext", sa.String(20)),
        sa.Column("file_size_bytes", sa.BigInteger),
        sa.Column("file_hash", sa.Text),
        sa.Column("stored_file_path", sa.Text),
        sa.Column("detected_employee_name", sa.Text),
        sa.Column("detected_vendor_name", sa.Text),
        sa.Column("detected_period_text", sa.Text),
        sa.Column("matched_employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id")),
        sa.Column("match_confidence", sa.Numeric(5, 4)),
        sa.Column("match_status", sa.String(20), default="NOT_MATCHED"),
        sa.Column("parser_name", sa.Text),
        sa.Column("ocr_required", sa.Boolean, default=False),
        sa.Column("is_duplicate", sa.Boolean, default=False),
        sa.Column("duplicate_of_file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id")),
        sa.Column("is_noise_file", sa.Boolean, default=False),
        sa.Column("is_timesheet_candidate", sa.Boolean, default=True),
        sa.Column("processing_status", sa.String(30), default="DETECTED"),
        sa.Column("alerts_json", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_uploaded_files_batch_id", "uploaded_files", ["batch_id"])
    op.create_index("idx_uploaded_files_hash", "uploaded_files", ["file_hash"])

    op.create_table(
        "file_processing_logs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id"), nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Extraction tables ──────────────────────────────────────────────────────
    op.create_table(
        "raw_extractions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id"), nullable=False),
        sa.Column("extraction_method", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text),
        sa.Column("raw_tables", JSONB),
        sa.Column("llm_json", JSONB),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("extraction_warnings", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "employee_file_matches",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id"), nullable=False),
        sa.Column("detected_name", sa.Text),
        sa.Column("matched_employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id")),
        sa.Column("match_method", sa.Text),
        sa.Column("match_confidence", sa.Numeric(5, 4)),
        sa.Column("review_status", sa.String(20), default="AUTO"),
        sa.Column("reviewed_by", UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Timesheet tables ───────────────────────────────────────────────────────
    op.create_table(
        "timesheet_submissions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("batch_uploads.id")),
        sa.Column("file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id")),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id")),
        sa.Column("payroll_period_id", UUID(as_uuid=False), sa.ForeignKey("payroll_periods.id")),
        sa.Column("vendor_id", UUID(as_uuid=False), sa.ForeignKey("vendors.id")),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("submission_date", sa.DateTime),
        sa.Column("timesheet_start_date", sa.Date),
        sa.Column("timesheet_end_date", sa.Date),
        sa.Column("approval_status", sa.String(20), default="PENDING"),
        sa.Column("approved_by_name", sa.Text),
        sa.Column("approved_by_email", sa.Text),
        sa.Column("approved_at", sa.DateTime),
        sa.Column("validation_status", sa.String(20), default="PENDING"),
        sa.Column("payroll_status", sa.String(20), default="NOT_READY"),
        sa.Column("is_late", sa.Boolean, default=False),
        sa.Column("payable_period_id", UUID(as_uuid=False), sa.ForeignKey("payroll_periods.id")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_timesheet_submissions_employee_period",
        "timesheet_submissions",
        ["employee_id", "payroll_period_id"],
    )

    op.create_table(
        "timesheet_entries",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("submission_id", UUID(as_uuid=False), sa.ForeignKey("timesheet_submissions.id"), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("day_of_week", sa.String(10)),
        sa.Column("in_time", sa.Time),
        sa.Column("out_time", sa.Time),
        sa.Column("break_minutes", sa.Integer, default=0),
        sa.Column("entered_hours", sa.Numeric(5, 2)),
        sa.Column("calculated_hours", sa.Numeric(5, 2)),
        sa.Column("regular_hours", sa.Numeric(5, 2), default=0),
        sa.Column("overtime_hours", sa.Numeric(5, 2), default=0),
        sa.Column("entry_type", sa.String(20), default="WORK"),
        sa.Column("leave_type", sa.String(30)),
        sa.Column("is_holiday", sa.Boolean, default=False),
        sa.Column("holiday_name", sa.Text),
        sa.Column("source_file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id")),
        sa.Column("row_source", JSONB),
        sa.Column("validation_status", sa.String(20), default="PENDING"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_timesheet_entries_employee_date",
        "timesheet_entries",
        ["employee_id", "work_date"],
    )

    # ── Validation / Approval tables ───────────────────────────────────────────
    op.create_table(
        "validation_errors",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("batch_uploads.id")),
        sa.Column("file_id", UUID(as_uuid=False), sa.ForeignKey("uploaded_files.id")),
        sa.Column("submission_id", UUID(as_uuid=False), sa.ForeignKey("timesheet_submissions.id")),
        sa.Column("entry_id", UUID(as_uuid=False), sa.ForeignKey("timesheet_entries.id")),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id")),
        sa.Column("rule_code", sa.Text, nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("expected_value", sa.Text),
        sa.Column("actual_value", sa.Text),
        sa.Column("action_required", sa.Text),
        sa.Column("assigned_to_role", sa.Text),
        sa.Column("status", sa.String(20), default="OPEN"),
        sa.Column("resolved_by", UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("resolved_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('INFO','WARNING','ERROR','BLOCKER')",
            name="ck_validation_errors_severity",
        ),
    )
    op.create_index("idx_validation_errors_status", "validation_errors", ["status"])

    op.create_table(
        "approval_records",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("submission_id", UUID(as_uuid=False), sa.ForeignKey("timesheet_submissions.id"), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("approver_name", sa.Text),
        sa.Column("approver_email", sa.Text),
        sa.Column("approval_status", sa.String(20), nullable=False),
        sa.Column("approval_source", sa.Text),
        sa.Column("approval_date", sa.DateTime),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "approval_status IN ('PENDING','APPROVED','REJECTED')",
            name="ck_approval_records_status",
        ),
    )

    # ── Payroll tables ─────────────────────────────────────────────────────────
    op.create_table(
        "payroll_runs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("payroll_period_id", UUID(as_uuid=False), sa.ForeignKey("payroll_periods.id"), nullable=False),
        sa.Column("run_by", UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("run_status", sa.String(20), default="DRAFT"),
        sa.Column("total_employees", sa.Integer, default=0),
        sa.Column("payroll_ready_employees", sa.Integer, default=0),
        sa.Column("blocked_employees", sa.Integer, default=0),
        sa.Column("total_regular_hours", sa.Numeric(10, 2), default=0),
        sa.Column("total_overtime_hours", sa.Numeric(10, 2), default=0),
        sa.Column("total_regular_pay", sa.Numeric(15, 4), default=0),
        sa.Column("total_overtime_pay", sa.Numeric(15, 4), default=0),
        sa.Column("total_pay", sa.Numeric(15, 4), default=0),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "payroll_results",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("payroll_run_id", UUID(as_uuid=False), sa.ForeignKey("payroll_runs.id"), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("vendor_id", UUID(as_uuid=False), sa.ForeignKey("vendors.id")),
        sa.Column("regular_hours", sa.Numeric(10, 2), default=0),
        sa.Column("overtime_hours", sa.Numeric(10, 2), default=0),
        sa.Column("leave_days", sa.Numeric(6, 2), default=0),
        sa.Column("holiday_hours", sa.Numeric(6, 2), default=0),
        sa.Column("regular_rate", sa.Numeric(10, 4)),
        sa.Column("overtime_rate", sa.Numeric(10, 4)),
        sa.Column("regular_pay", sa.Numeric(15, 4), default=0),
        sa.Column("overtime_pay", sa.Numeric(15, 4), default=0),
        sa.Column("total_pay", sa.Numeric(15, 4), default=0),
        sa.Column("payroll_status", sa.String(20), default="READY"),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_payroll_results_run", "payroll_results", ["payroll_run_id"])

    op.create_table(
        "generated_reports",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("batch_uploads.id")),
        sa.Column("payroll_run_id", UUID(as_uuid=False), sa.ForeignKey("payroll_runs.id")),
        sa.Column("report_type", sa.Text, nullable=False),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("generated_by", UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Audit / Notification tables ────────────────────────────────────────────
    op.create_table(
        "notification_logs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=False), sa.ForeignKey("employees.id")),
        sa.Column("recipient_email", sa.Text, nullable=False),
        sa.Column("notification_type", sa.Text, nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("status", sa.String(20), default="PENDING"),
        sa.Column("sent_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("actor_user_id", UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", UUID(as_uuid=False)),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("before_json", JSONB),
        sa.Column("after_json", JSONB),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    tables = [
        "audit_logs", "notification_logs", "generated_reports",
        "payroll_results", "payroll_runs", "approval_records",
        "validation_errors", "timesheet_entries", "timesheet_submissions",
        "employee_file_matches", "raw_extractions", "file_processing_logs",
        "uploaded_files", "batch_uploads", "payroll_periods",
        "holiday_dates", "holiday_calendars", "employee_rates",
        "employees", "client_managers", "vendors", "users",
    ]
    for t in tables:
        op.drop_table(t)

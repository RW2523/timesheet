"""Add email integration tables (email_accounts, email_crawl_jobs, email_messages).

These tables were previously only created at runtime via Base.metadata.create_all,
so a migrations-only deploy lacked them and the Gmail crawl feature would fail.
This migration brings Alembic back in sync with the ORM models.

Revision ID: 003
Revises: 002
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    # Guard each create — runtime create_all may already have made these.
    if not _has_table("email_accounts"):
        op.create_table(
            "email_accounts",
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("email_address", sa.Text(), nullable=False, unique=True),
            sa.Column("provider", sa.String(20), server_default="gmail"),
            sa.Column("access_token", sa.Text()),
            sa.Column("refresh_token", sa.Text()),
            sa.Column("token_expiry", sa.DateTime()),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
            sa.Column("last_crawled_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    if not _has_table("email_crawl_jobs"):
        op.create_table(
            "email_crawl_jobs",
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column("account_id", UUID(as_uuid=False),
                      sa.ForeignKey("email_accounts.id"), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("subject_filter", sa.Text()),
            sa.Column("status", sa.String(20), server_default="PENDING"),
            sa.Column("emails_scanned", sa.Integer(), server_default="0"),
            sa.Column("emails_timesheet", sa.Integer(), server_default="0"),
            sa.Column("emails_skipped", sa.Integer(), server_default="0"),
            sa.Column("attachments_saved", sa.Integer(), server_default="0"),
            sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("batch_uploads.id")),
            sa.Column("triggered_by", sa.String(20), server_default="MANUAL"),
            sa.Column("error_message", sa.Text()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
        )
        op.create_index("idx_email_crawl_account", "email_crawl_jobs", ["account_id"])

    if not _has_table("email_messages"):
        op.create_table(
            "email_messages",
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column("crawl_job_id", UUID(as_uuid=False),
                      sa.ForeignKey("email_crawl_jobs.id"), nullable=False),
            sa.Column("account_id", UUID(as_uuid=False),
                      sa.ForeignKey("email_accounts.id"), nullable=False),
            sa.Column("gmail_message_id", sa.Text(), nullable=False, unique=True),
            sa.Column("subject", sa.Text()),
            sa.Column("sender_name", sa.Text()),
            sa.Column("sender_email", sa.Text()),
            sa.Column("received_at", sa.DateTime()),
            sa.Column("body_snippet", sa.Text()),
            sa.Column("is_timesheet", sa.Boolean()),
            sa.Column("classification_reason", sa.Text()),
            sa.Column("classification_method", sa.String(20)),
            sa.Column("classification_confidence", sa.Numeric(4, 3)),
            sa.Column("has_attachments", sa.Boolean(), server_default=sa.false()),
            sa.Column("attachments_metadata", JSONB()),
            sa.Column("processing_status", sa.String(20), server_default="PENDING"),
            sa.Column("batch_id", UUID(as_uuid=False), sa.ForeignKey("batch_uploads.id")),
            sa.Column("skip_reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("idx_email_messages_sender", "email_messages", ["sender_email"])
        op.create_index("idx_email_messages_job", "email_messages", ["crawl_job_id"])


def downgrade() -> None:
    op.drop_table("email_messages")
    op.drop_table("email_crawl_jobs")
    op.drop_table("email_accounts")

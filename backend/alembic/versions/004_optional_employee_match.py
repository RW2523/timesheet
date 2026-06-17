"""Make employee matching optional metadata, not a gate on extraction.

- timesheet_entries.employee_id -> nullable (a timesheet is fully extracted
  even when no employee match exists).
- timesheet_submissions.detected_employee_name -> store the name extracted
  from the document regardless of match.

Revision ID: 004_optional_employee_match
Revises: 003_email_integration
"""
from alembic import op
import sqlalchemy as sa


revision = "004_optional_employee_match"
down_revision = "003_email_integration"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    op.alter_column("timesheet_entries", "employee_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)
    if not _has_column("timesheet_submissions", "detected_employee_name"):
        op.add_column("timesheet_submissions", sa.Column("detected_employee_name", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("timesheet_submissions", "detected_employee_name"):
        op.drop_column("timesheet_submissions", "detected_employee_name")
    op.alter_column("timesheet_entries", "employee_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)

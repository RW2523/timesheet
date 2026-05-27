"""Add live progress and period filter columns to batch_uploads.

Revision ID: 002
Revises: 001
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("batch_uploads", sa.Column("current_file", sa.Text(), nullable=True))
    op.add_column("batch_uploads", sa.Column("current_stage", sa.Text(), nullable=True))
    op.add_column("batch_uploads", sa.Column("filter_period_start", sa.Text(), nullable=True))
    op.add_column("batch_uploads", sa.Column("filter_period_end", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("batch_uploads", "filter_period_end")
    op.drop_column("batch_uploads", "filter_period_start")
    op.drop_column("batch_uploads", "current_stage")
    op.drop_column("batch_uploads", "current_file")

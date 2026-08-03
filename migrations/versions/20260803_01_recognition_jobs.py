"""add PostgreSQL-backed recognition jobs

Revision ID: 20260803_01
Revises: 20260730_01
Create Date: 2026-08-03 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_01"
down_revision: Union[str, Sequence[str], None] = "20260730_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recognition_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("drawing_name", sa.String(length=512), nullable=True),
        sa.Column("artifact_dir", sa.Text(), nullable=True),
        sa.Column("input_filename", sa.String(length=512), nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("file_info", sa.JSON(), nullable=True),
        sa.Column("owner_erp_user_id", sa.String(length=256), nullable=True),
        sa.Column("owner_username", sa.String(length=256), nullable=True),
        sa.Column("owner_real_name", sa.String(length=256), nullable=True),
        sa.Column("owner_org_id", sa.String(length=256), nullable=True),
        sa.Column("owner_org_name", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_recognition_jobs_status_created", "recognition_jobs", ["status", "created_at"])
    op.create_index("ix_recognition_jobs_owner_updated", "recognition_jobs", ["owner_erp_user_id", "updated_at"])
    op.create_index("ix_recognition_jobs_lease", "recognition_jobs", ["status", "lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_recognition_jobs_lease", table_name="recognition_jobs")
    op.drop_index("ix_recognition_jobs_owner_updated", table_name="recognition_jobs")
    op.drop_index("ix_recognition_jobs_status_created", table_name="recognition_jobs")
    op.drop_table("recognition_jobs")

"""add generation templates, jobs, artifacts, and events

Revision ID: 20260804_01
Revises: 20260803_01
Create Date: 2026-08-04 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260804_01"
down_revision: Union[str, Sequence[str], None] = "20260803_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_code", sa.String(length=192), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("drawing_type", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("required_fields", sa.JSON(), nullable=False),
        sa.Column("match_rules", sa.JSON(), nullable=False),
        sa.Column("parameter_mapping", sa.JSON(), nullable=False),
        sa.Column("worker_capability", sa.String(length=192), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_code", "version", name="uq_generation_template_version"),
    )
    op.create_index("ix_generation_templates_enabled_type", "generation_templates", ["enabled", "drawing_type"])

    op.create_table(
        "generation_jobs",
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("review_job_id", sa.String(length=64), nullable=False),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("parent_generation_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("owner_erp_user_id", sa.String(length=256), nullable=False),
        sa.Column("owner_username", sa.String(length=256), nullable=True),
        sa.Column("owner_real_name", sa.String(length=256), nullable=True),
        sa.Column("owner_org_id", sa.String(length=256), nullable=True),
        sa.Column("owner_org_name", sa.String(length=256), nullable=True),
        sa.Column("template_code", sa.String(length=192), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("worker_capability", sa.String(length=192), nullable=False),
        sa.Column("parameter_schema_version", sa.String(length=96), nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("parameter_package", sa.JSON(), nullable=False),
        sa.Column("readiness", sa.JSON(), nullable=False),
        sa.Column("requested_artifact_types", sa.JSON(), nullable=False),
        sa.Column("execution_options", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.JSON(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_job_id"], ["drawing_reviews.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_generation_id"], ["generation_jobs.generation_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("generation_id"),
        sa.UniqueConstraint("owner_erp_user_id", "review_job_id", "idempotency_key", name="uq_generation_job_idempotency"),
    )
    op.create_index("ix_generation_jobs_status_created", "generation_jobs", ["status", "created_at"])
    op.create_index("ix_generation_jobs_review_created", "generation_jobs", ["review_job_id", "created_at"])
    op.create_index("ix_generation_jobs_lease", "generation_jobs", ["status", "lease_expires_at"])
    op.create_index(
        "uq_generation_jobs_final_review",
        "generation_jobs",
        ["review_job_id"],
        unique=True,
        postgresql_where=sa.text("is_final"),
    )

    op.create_table(
        "generation_artifacts",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=256), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_id"], ["generation_jobs.generation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    op.create_index("ix_generation_artifacts_job", "generation_artifacts", ["generation_id", "created_at"])

    op.create_table(
        "generation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_id"], ["generation_jobs.generation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_id", "sequence", name="uq_generation_event_sequence"),
    )
    op.create_index("ix_generation_events_job", "generation_events", ["generation_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_generation_events_job", table_name="generation_events")
    op.drop_table("generation_events")
    op.drop_index("ix_generation_artifacts_job", table_name="generation_artifacts")
    op.drop_table("generation_artifacts")
    op.drop_index("ix_generation_jobs_lease", table_name="generation_jobs")
    op.drop_index("uq_generation_jobs_final_review", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_review_created", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_status_created", table_name="generation_jobs")
    op.drop_table("generation_jobs")
    op.drop_index("ix_generation_templates_enabled_type", table_name="generation_templates")
    op.drop_table("generation_templates")

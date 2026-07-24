"""add review persistence and audit events

Revision ID: 20260724_01
Revises:
Create Date: 2026-07-24 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260724_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drawing_reviews",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("drawing_no", sa.String(length=128), nullable=True),
        sa.Column("drawing_name", sa.String(length=512), nullable=True),
        sa.Column("spring_type", sa.String(length=64), nullable=True),
        sa.Column("artifact_dir", sa.Text(), nullable=True),
        sa.Column("file_info", sa.JSON(), nullable=True),
        sa.Column("review_snapshot", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "review_change_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("review_job_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("revision_before", sa.Integer(), nullable=False),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("target_field", sa.String(length=192), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_job_id"], ["drawing_reviews.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_job_id", "sequence", name="uq_review_change_event_sequence"),
    )
    op.create_index("ix_review_change_events_review_job_id", "review_change_events", ["review_job_id"])


def downgrade() -> None:
    op.drop_index("ix_review_change_events_review_job_id", table_name="review_change_events")
    op.drop_table("review_change_events")
    op.drop_table("drawing_reviews")

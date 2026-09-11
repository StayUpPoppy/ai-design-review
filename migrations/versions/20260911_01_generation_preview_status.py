"""track generated PDF comparison preview status

Revision ID: 20260911_01
Revises: 20260909_01
Create Date: 2026-09-11 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260911_01"
down_revision: Union[str, Sequence[str], None] = "20260909_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column("preview_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("preview_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("generation_jobs", sa.Column("preview_error_message", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE generation_jobs AS job
        SET preview_status = CASE
            WHEN EXISTS (
                SELECT 1 FROM generation_artifacts AS artifact
                WHERE artifact.generation_id = job.generation_id
                  AND artifact.artifact_type = 'png'
            ) THEN 'ready'
            WHEN job.status = 'completed' AND EXISTS (
                SELECT 1 FROM generation_artifacts AS artifact
                WHERE artifact.generation_id = job.generation_id
                  AND artifact.artifact_type = 'pdf'
            ) THEN 'failed'
            ELSE 'pending'
        END,
        preview_error_message = CASE
            WHEN job.status = 'completed'
              AND EXISTS (
                  SELECT 1 FROM generation_artifacts AS artifact
                  WHERE artifact.generation_id = job.generation_id
                    AND artifact.artifact_type = 'pdf'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM generation_artifacts AS artifact
                  WHERE artifact.generation_id = job.generation_id
                    AND artifact.artifact_type = 'png'
              )
            THEN '历史任务缺少对比预览，可重新生成。'
            ELSE NULL
        END
        """
    )


def downgrade() -> None:
    op.drop_column("generation_jobs", "preview_error_message")
    op.drop_column("generation_jobs", "preview_attempt_count")
    op.drop_column("generation_jobs", "preview_status")

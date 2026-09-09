"""add ten digit SolidWorks task id sequence

Revision ID: 20260909_01
Revises: 20260804_01
Create Date: 2026-09-09 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260909_01"
down_revision: Union[str, Sequence[str], None] = "20260804_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE SEQUENCE solidworks_task_id_seq "
        "START WITH 1000000000 MINVALUE 1000000000 MAXVALUE 9999999999 NO CYCLE"
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE solidworks_task_id_seq")

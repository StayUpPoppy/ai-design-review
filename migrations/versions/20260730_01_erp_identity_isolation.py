"""add ERP identity ownership to drawing reviews

Revision ID: 20260730_01
Revises: 20260724_01
Create Date: 2026-07-30 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_01"
down_revision: Union[str, Sequence[str], None] = "20260724_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drawing_reviews", sa.Column("owner_erp_user_id", sa.String(length=256), nullable=True))
    op.add_column("drawing_reviews", sa.Column("owner_username", sa.String(length=256), nullable=True))
    op.add_column("drawing_reviews", sa.Column("owner_real_name", sa.String(length=256), nullable=True))
    op.add_column("drawing_reviews", sa.Column("owner_org_id", sa.String(length=256), nullable=True))
    op.add_column("drawing_reviews", sa.Column("owner_org_name", sa.String(length=256), nullable=True))
    op.create_index(
        "ix_drawing_reviews_owner_updated",
        "drawing_reviews",
        ["owner_erp_user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_drawing_reviews_owner_updated", table_name="drawing_reviews")
    op.drop_column("drawing_reviews", "owner_org_name")
    op.drop_column("drawing_reviews", "owner_org_id")
    op.drop_column("drawing_reviews", "owner_real_name")
    op.drop_column("drawing_reviews", "owner_username")
    op.drop_column("drawing_reviews", "owner_erp_user_id")

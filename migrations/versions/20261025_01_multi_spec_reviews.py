"""Add source/variant relationships, preserving existing single reviews."""
from alembic import op
import sqlalchemy as sa

revision = "20261025_01"
down_revision = "20260911_01"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("drawing_reviews") as batch:
        batch.add_column(sa.Column("record_kind", sa.String(16), nullable=False, server_default="single"))
        batch.add_column(sa.Column("parent_review_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("variant_id", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_review_source", "drawing_reviews", ["parent_review_id"], ["job_id"], ondelete="CASCADE")
        batch.create_index("ix_drawing_reviews_parent", ["parent_review_id"])
        batch.create_unique_constraint("uq_review_source_variant", ["parent_review_id", "variant_id"])


def downgrade():
    with op.batch_alter_table("drawing_reviews") as batch:
        batch.drop_constraint("uq_review_source_variant", type_="unique")
        batch.drop_index("ix_drawing_reviews_parent")
        batch.drop_constraint("fk_review_source", type_="foreignkey")
        batch.drop_column("variant_id")
        batch.drop_column("parent_review_id")
        batch.drop_column("record_kind")

"""Store independently rendered template PDF snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "20261122_01"
down_revision = "20261108_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("template_pdf_drawings",
        sa.Column("pdf_id", sa.String(64), primary_key=True),
        sa.Column("review_job_id", sa.String(64), sa.ForeignKey("drawing_reviews.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_erp_user_id", sa.String(256), nullable=False),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("parameter_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_requirements_text", sa.Text(), nullable=False),
        sa.Column("template_data", sa.JSON(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_erp_user_id", "review_job_id", "idempotency_key", name="uq_template_pdf_request"))
    op.create_index("ix_template_pdf_review_created", "template_pdf_drawings", ["review_job_id", "created_at"])


def downgrade():
    op.drop_table("template_pdf_drawings")

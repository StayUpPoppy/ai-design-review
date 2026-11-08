"""Add the shared material catalog; data is initialized separately."""
from alembic import op
import sqlalchemy as sa

revision = "20261108_01"
down_revision = "20261025_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "spring_materials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("standard_value", sa.String(256), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("shear_modulus_mpa", sa.Float(), nullable=False),
        sa.Column("density_g_cm3", sa.Float(), nullable=False),
        sa.Column("tensile_strength_mpa", sa.Float(), nullable=True),
        sa.Column("elastic_modulus_mpa", sa.Float(), nullable=True),
        sa.Column("allowable_shear_stress_mpa", sa.Float(), nullable=True),
        sa.Column("allowable_stress_coefficient", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_display_name", sa.String(256), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("display_name", name="uq_spring_material_name"),
        sa.CheckConstraint("shear_modulus_mpa > 0", name="ck_spring_material_g"),
        sa.CheckConstraint("density_g_cm3 > 0", name="ck_spring_material_density"),
        *(sa.CheckConstraint(f"{field} IS NULL OR {field} > 0", name=f"ck_spring_material_{field}")
          for field in ("tensile_strength_mpa", "elastic_modulus_mpa", "allowable_shear_stress_mpa", "allowable_stress_coefficient")),
    )


def downgrade():
    op.drop_table("spring_materials")

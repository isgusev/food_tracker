"""штрихкод продукта; шаблоны недель плана

Revision ID: 0009_barcode_templates
Revises: 0008_budget
Create Date: 2026-10-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_barcode_templates"
down_revision = "0008_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("barcode", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_products_barcode", "products", ["barcode"])
    op.create_table(
        "week_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"],
            name="fk_week_templates_household_id_households", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_week_templates"),
    )
    op.create_index("ix_week_templates_id", "week_templates", ["id"])
    op.create_index("ix_week_templates_household_id", "week_templates", ["household_id"])


def downgrade() -> None:
    op.drop_table("week_templates")
    op.drop_constraint("uq_products_barcode", "products", type_="unique")
    op.drop_column("products", "barcode")

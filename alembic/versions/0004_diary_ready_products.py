"""diary_logs: готовые продукты в плане/дневнике (variant_id)

Revision ID: 0004_diary_ready_products
Revises: 0003_pot_is_discarded
Create Date: 2026-10-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_diary_ready_products"
down_revision = "0003_pot_is_discarded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("diary_logs") as batch:
        batch.add_column(sa.Column("variant_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_diary_logs_variant_id_product_variants",
            "product_variants",
            ["variant_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("diary_logs") as batch:
        batch.drop_constraint("fk_diary_logs_variant_id_product_variants", type_="foreignkey")
        batch.drop_column("variant_id")

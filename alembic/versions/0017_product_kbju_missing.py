"""продукт без КБЖУ «на потом» (из чека / внеплановой покупки)

Revision ID: 0017_product_kbju_missing
Revises: 0016_shopping_line_added
Create Date: 2026-11-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_product_kbju_missing"
down_revision = "0016_shopping_line_added"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("kbju_missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("products", "kbju_missing")

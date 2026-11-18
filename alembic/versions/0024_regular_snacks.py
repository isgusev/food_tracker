"""автоплан, этап 3: «обычно берём» у товара семьи, снеки и квота

Revision ID: 0024_regular_snacks
Revises: 0023_planner_settings
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_regular_snacks"
down_revision = "0023_planner_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("household_products", sa.Column("regular", sa.String(8), nullable=False, server_default="auto"))
    op.add_column("household_products", sa.Column("regular_qty", sa.Numeric(9, 1), nullable=True))
    op.add_column("household_products", sa.Column("is_snack", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("planner_settings", sa.Column("snack_categories", sa.JSON(), nullable=True))
    op.add_column("planner_settings", sa.Column("snack_quota", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("planner_settings", "snack_quota")
    op.drop_column("planner_settings", "snack_categories")
    op.drop_column("household_products", "is_snack")
    op.drop_column("household_products", "regular_qty")
    op.drop_column("household_products", "regular")

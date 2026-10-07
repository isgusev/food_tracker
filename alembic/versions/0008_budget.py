"""households.monthly_budget — бюджет семьи на продукты в месяц

Revision ID: 0008_budget
Revises: 0007_stock
Create Date: 2026-10-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_budget"
down_revision = "0007_stock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("households", sa.Column("monthly_budget", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("households", "monthly_budget")

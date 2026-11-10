"""строка покупок: добавлено вручную поверх расчёта по плану

Revision ID: 0016_shopping_line_added
Revises: 0015_items
Create Date: 2026-11-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_shopping_line_added"
down_revision = "0015_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shopping_lines", sa.Column("added", sa.Numeric(9, 1), nullable=True))


def downgrade() -> None:
    op.drop_column("shopping_lines", "added")

"""рецепт можно готовить половиной (покупки — до половины закладки)

Revision ID: 0014_recipe_allow_half
Revises: 0013_receipts
Create Date: 2026-11-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_recipe_allow_half"
down_revision = "0013_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column("allow_half", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("recipes", "allow_half")

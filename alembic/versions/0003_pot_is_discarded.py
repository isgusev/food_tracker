"""recipe_cooking_logs: признак удалённой кастрюли (is_discarded) для архива холодильника

Revision ID: 0003_pot_is_discarded
Revises: 0002_recipe_user_id
Create Date: 2026-10-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_pot_is_discarded"
down_revision = "0002_recipe_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipe_cooking_logs",
        sa.Column(
            "is_discarded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("recipe_cooking_logs", "is_discarded")

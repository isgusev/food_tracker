"""автоплан, этап 2: настройки планировщика семьи

Revision ID: 0023_planner_settings
Revises: 0022_autoplan_fields
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_planner_settings"
down_revision = "0022_autoplan_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planner_settings",
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("households.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("meal_types", sa.JSON(), nullable=True),
        sa.Column("no_cook_days", sa.JSON(), nullable=True),
        sa.Column("special_days", sa.JSON(), nullable=True),
        sa.Column("max_special_per_week", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("planner_settings")

"""автоплан: поля рецепта, происхождение блюда плана, заготовки в морозилке

Revision ID: 0022_autoplan_fields
Revises: 0021_portion_tolerance
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0022_autoplan_fields"
down_revision = "0021_portion_tolerance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("in_rotation", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("recipes", sa.Column("effort", sa.String(10), nullable=False, server_default="easy"))
    op.add_column("recipes", sa.Column("meal_types", sa.JSON(), nullable=True))
    op.add_column("recipes", sa.Column("keeps_days", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("recipes", sa.Column("is_freezable", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("meal_items", sa.Column("origin", sa.String(10), nullable=False, server_default="manual"))
    op.add_column("meal_items", sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("meal_items", sa.Column("auto_reason", sa.String(200), nullable=True))
    op.add_column("recipe_cooking_logs", sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("recipe_cooking_logs", sa.Column("keeps_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipe_cooking_logs", "keeps_until")
    op.drop_column("recipe_cooking_logs", "is_frozen")
    op.drop_column("meal_items", "auto_reason")
    op.drop_column("meal_items", "pinned")
    op.drop_column("meal_items", "origin")
    op.drop_column("recipes", "is_freezable")
    op.drop_column("recipes", "keeps_days")
    op.drop_column("recipes", "meal_types")
    op.drop_column("recipes", "effort")
    op.drop_column("recipes", "in_rotation")

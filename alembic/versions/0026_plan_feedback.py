"""автоплан, этап 4: отзывы о предложениях (plan_feedback)

Revision ID: 0026_plan_feedback
Revises: 0025_indexes_checks
Create Date: 2026-11-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_plan_feedback"
down_revision = "0025_indexes_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("households.id", ondelete="CASCADE",
                  name="fk_plan_feedback_household_id_households"), nullable=False),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id", ondelete="CASCADE",
                  name="fk_plan_feedback_recipe_id_recipes"), nullable=True),
        sa.Column("item_key", sa.String(255), nullable=True),
        sa.Column("meal_type", sa.String(20), nullable=True),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("action IN ('accepted', 'pinned', 'replaced', 'removed')", name=op.f("ck_plan_feedback_action")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_feedback")),
    )
    op.create_index("ix_plan_feedback_household_created", "plan_feedback", ["household_id", "created_at"])
    op.create_index("ix_plan_feedback_recipe_id", "plan_feedback", ["recipe_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_feedback_recipe_id", table_name="plan_feedback")
    op.drop_index("ix_plan_feedback_household_created", table_name="plan_feedback")
    op.drop_table("plan_feedback")

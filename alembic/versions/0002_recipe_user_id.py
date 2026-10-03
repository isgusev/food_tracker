"""recipes: привязка к владельцу (user_id) — рецепты становятся личными

Revision ID: 0002_recipe_user_id
Revises: 0001_initial_schema
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_recipe_user_id"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Временная nullable-колонка
    op.add_column(
        "recipes",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    # 2) Заполняем владельцем: у кастрюль (recipe_cooking_logs) user_id уже есть;
    #    сироты получают первого пользователя (детерминированно по id).
    op.execute(
        """
        UPDATE recipes r
        SET user_id = src.owner_id
        FROM (
            SELECT DISTINCT ON (cl.recipe_id) cl.recipe_id, cl.user_id AS owner_id
            FROM recipe_cooking_logs cl
            WHERE cl.recipe_id IS NOT NULL
            ORDER BY cl.recipe_id, cl.id
        ) src
        WHERE r.id = src.recipe_id
        """
    )
    op.execute(
        """
        UPDATE recipes
        SET user_id = (SELECT MIN(u.id) FROM users u)
        WHERE user_id IS NULL
        """
    )
    # Если пользователей нет вообще — не даём колонке остаться NULL: удаляем рецепты
    # (FK потребует NOT NULL; на пустой БД это no-op).
    op.execute("DELETE FROM recipes WHERE user_id IS NULL")
    op.alter_column("recipes", "user_id", existing_type=sa.Integer(), nullable=False)
    op.create_index(op.f("ix_recipes_user_id"), "recipes", ["user_id"])
    op.create_foreign_key(
        "fk_recipes_user_id_users",
        "recipes",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_recipes_user_id_users", "recipes", type_="foreignkey")
    op.drop_index(op.f("ix_recipes_user_id"), table_name="recipes")
    op.drop_column("recipes", "user_id")

"""рефакторинг Р4: индексы на частые выборки, CHECK для строковых «перечислений», автор рецепта — SET NULL

- Индексы: план семьи за период (household_id, date_day), блюда по рецепту/продукту, состав рецепта и кастрюли,
  кастрюли по рецепту, строки списка по продукту — PostgreSQL сам индексы на внешние ключи не создаёт.
- CHECK: приём пищи и происхождение блюда, «эдакое», «обычно берём», источник партии, причина движения, статусы
  списка и чека, пол и цель члена семьи, единица товара. Добавляются как NOT VALID: новые строки проверяются,
  уже лежащие на стенде — нет (миграция не упадёт на старых данных). Проверить их можно потом:
  ALTER TABLE … VALIDATE CONSTRAINT ….
- recipes.user_id, recipe_cooking_logs.user_id: ON DELETE CASCADE → SET NULL (удаление пользователя не стирает
  рецепты и кастрюли всей семьи).

Revision ID: 0025_indexes_checks
Revises: 0024_regular_snacks
Create Date: 2026-11-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_indexes_checks"
down_revision = "0024_regular_snacks"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_meal_items_household_date", "meal_items", ["household_id", "date_day"]),
    ("ix_meal_items_recipe_id", "meal_items", ["recipe_id"]),
    ("ix_meal_items_variant_id", "meal_items", ["variant_id"]),
    ("ix_recipe_template_ingredients_recipe_id", "recipe_template_ingredients", ["recipe_id"]),
    ("ix_recipe_template_ingredients_variant_id", "recipe_template_ingredients", ["variant_id"]),
    ("ix_recipe_cooking_logs_recipe_id", "recipe_cooking_logs", ["recipe_id"]),
    ("ix_recipe_actual_ingredients_cooking_log_id", "recipe_actual_ingredients", ["cooking_log_id"]),
    ("ix_shopping_lines_product_id", "shopping_lines", ["product_id"]),
]

CHECKS = [
    ("ck_meal_items_meal_type", "meal_items", "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')"),
    ("ck_meal_items_origin", "meal_items", "origin IN ('manual', 'auto')"),
    ("ck_recipes_effort", "recipes", "effort IN ('easy', 'special')"),
    ("ck_household_products_regular", "household_products", "regular IN ('auto', 'always', 'never')"),
    ("ck_stock_lots_source", "stock_lots", "source IN ('purchase', 'manual', 'inventory')"),
    ("ck_stock_movements_reason", "stock_movements",
     "reason IN ('purchase', 'manual', 'inventory', 'cook', 'eat', 'write_off')"),
    ("ck_shopping_lists_status", "shopping_lists", "status IN ('active', 'closed')"),
    ("ck_receipts_status", "receipts", "status IN ('pending', 'done', 'error', 'applied')"),
    ("ck_household_members_sex", "household_members", "sex IN ('m', 'f')"),
    ("ck_household_members_goal", "household_members", "goal IN ('maintain', 'lose', 'gain')"),
    ("ck_products_base_unit", "products", "base_unit IN ('g', 'ml', 'pcs')"),
]

AUTHOR_FKS = [
    ("fk_recipes_user_id_users", "recipes"),
    ("fk_recipe_cooking_logs_user_id_users", "recipe_cooking_logs"),
]


def upgrade() -> None:
    for name, table, cols in INDEXES:
        op.create_index(name, table, cols)
    for name, table, expr in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID")
    for fk, table in AUTHOR_FKS:
        op.drop_constraint(fk, table, type_="foreignkey")
        op.alter_column(table, "user_id", existing_type=sa.Integer(), nullable=True)
        op.create_foreign_key(fk, table, "users", ["user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    for fk, table in AUTHOR_FKS:
        op.drop_constraint(fk, table, type_="foreignkey")
        # автор мог исчезнуть — без него NOT NULL не вернуть: такие строки получают первого пользователя
        op.execute(f"UPDATE {table} SET user_id = (SELECT MIN(id) FROM users) WHERE user_id IS NULL")
        op.alter_column(table, "user_id", existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(fk, table, "users", ["user_id"], ["id"], ondelete="CASCADE")
    for name, table, _ in reversed(CHECKS):
        op.drop_constraint(op.f(name), table, type_="check")   # имя уже полное — без naming_convention
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)

"""diary_logs.date_day → DATE; веса кастрюль и ингредиентов до 99 999,9 г

Revision ID: 0005_date_and_weights
Revises: 0004_diary_ready_products
Create Date: 2026-10-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_date_and_weights"
down_revision = "0004_diary_ready_products"
branch_labels = None
depends_on = None

# (таблица, колонка, старая точность) — расширяем до Numeric(7, 1)
WEIGHTS = [
    ("recipes", "total_raw_weight", 6),
    ("recipes", "estimated_cooked_weight", 6),
    ("recipe_template_ingredients", "weight_g", 5),
    ("recipe_cooking_logs", "total_raw_weight", 6),
    ("recipe_cooking_logs", "total_cooked_weight", 6),
    ("recipe_cooking_logs", "current_remaining_weight", 6),
    ("recipe_actual_ingredients", "weight_g", 5),
]


def upgrade() -> None:
    # Строки 'YYYY-MM-DD' валидировались схемой API, поэтому приведение безопасно
    op.alter_column(
        "diary_logs",
        "date_day",
        type_=sa.Date(),
        existing_type=sa.String(10),
        existing_nullable=False,
        postgresql_using="date_day::date",
    )
    for table, column, old in WEIGHTS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(7, 1),
            existing_type=sa.Numeric(old, 1),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Сужение упадёт, если в БД уже есть веса больше старого предела — это ожидаемо
    for table, column, old in WEIGHTS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(old, 1),
            existing_type=sa.Numeric(7, 1),
            existing_nullable=False,
        )
    op.alter_column(
        "diary_logs",
        "date_day",
        type_=sa.String(10),
        existing_type=sa.Date(),
        existing_nullable=False,
        postgresql_using="to_char(date_day, 'YYYY-MM-DD')",
    )

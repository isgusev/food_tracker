"""товары (базовые наименования) и «именно этот вариант»

Revision ID: 0015_items
Revises: 0014_recipe_allow_half
Create Date: 2026-11-10

Перенос без потерь: раньше товаром было название продукта без бренда
(products.search_name) — каждое такое название становится товаром с тем же
ключом, поэтому запасы, «базовые» (household_products.item_key) и цены не меняются.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_items"
down_revision = "0014_recipe_allow_half"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    # название товара — самое короткое из названий его продуктов (обычно без лишнего)
    op.execute(
        """
        INSERT INTO items (key, name)
        SELECT DISTINCT ON (search_name) search_name, name
        FROM products
        ORDER BY search_name, length(name), name
        """
    )
    op.add_column("products", sa.Column("item_key", sa.String(255), nullable=True))
    op.execute("UPDATE products SET item_key = search_name")
    op.alter_column("products", "item_key", nullable=False)
    op.create_foreign_key("products_item_key_fkey", "products", "items", ["item_key"], ["key"], ondelete="RESTRICT")
    op.create_index(op.f("ix_products_item_key"), "products", ["item_key"], unique=False)

    for table, column in (
        ("recipe_template_ingredients", "exact"),
        ("meal_items", "exact"),
        ("shopping_lines", "is_exact"),
    ):
        op.add_column(table, sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("shopping_lines", "is_exact")
    op.drop_column("meal_items", "exact")
    op.drop_column("recipe_template_ingredients", "exact")
    op.drop_index(op.f("ix_products_item_key"), table_name="products")
    op.drop_constraint("products_item_key_fkey", "products", type_="foreignkey")
    op.drop_column("products", "item_key")
    op.drop_table("items")

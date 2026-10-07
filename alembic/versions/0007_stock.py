"""запасы: единицы и упаковки продуктов, партии и движения запасов, общий список покупок

Revision ID: 0007_stock
Revises: 0006_households
Create Date: 2026-10-07

Существующие продукты получают единицу «г»; запасы стартуют пустыми, поэтому
список покупок остаётся прежним, пока не внесены покупки или инвентаризация.
DDL новых таблиц сгенерирован из моделей (dialect=postgresql).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_stock"
down_revision = "0006_households"
branch_labels = None
depends_on = None

NEW_TABLES_SQL = """
CREATE TABLE product_packages (
	id SERIAL NOT NULL, 
	product_id INTEGER NOT NULL, 
	amount NUMERIC(9, 1) NOT NULL, 
	name VARCHAR(50), 
	CONSTRAINT pk_product_packages PRIMARY KEY (id), 
	CONSTRAINT _product_package_amount_uc UNIQUE (product_id, amount), 
	CONSTRAINT fk_product_packages_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
CREATE INDEX ix_product_packages_id ON product_packages (id);
CREATE INDEX ix_product_packages_product_id ON product_packages (product_id);
CREATE TABLE household_products (
	household_id INTEGER NOT NULL, 
	item_key VARCHAR(255) NOT NULL, 
	is_staple BOOLEAN NOT NULL, 
	is_low BOOLEAN NOT NULL, 
	needs_check BOOLEAN NOT NULL, 
	CONSTRAINT pk_household_products PRIMARY KEY (household_id, item_key), 
	CONSTRAINT fk_household_products_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);
CREATE TABLE stock_lots (
	id SERIAL NOT NULL, 
	household_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	variant_id INTEGER, 
	quantity NUMERIC(9, 1) NOT NULL, 
	remaining NUMERIC(9, 1) NOT NULL, 
	price NUMERIC(10, 2), 
	purchased_on DATE NOT NULL, 
	expires_on DATE, 
	source VARCHAR(16) NOT NULL, 
	created_by_user_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	CONSTRAINT pk_stock_lots PRIMARY KEY (id), 
	CONSTRAINT fk_stock_lots_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stock_lots_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stock_lots_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE SET NULL, 
	CONSTRAINT fk_stock_lots_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_stock_lots_household_id ON stock_lots (household_id);
CREATE INDEX ix_stock_lots_id ON stock_lots (id);
CREATE INDEX ix_stock_lots_product_id ON stock_lots (product_id);
CREATE TABLE stock_movements (
	id SERIAL NOT NULL, 
	household_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	lot_id INTEGER, 
	delta NUMERIC(9, 1) NOT NULL, 
	reason VARCHAR(16) NOT NULL, 
	pot_id INTEGER, 
	portion_id INTEGER, 
	note VARCHAR(200), 
	created_by_user_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	CONSTRAINT pk_stock_movements PRIMARY KEY (id), 
	CONSTRAINT fk_stock_movements_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stock_movements_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stock_movements_lot_id_stock_lots FOREIGN KEY(lot_id) REFERENCES stock_lots (id) ON DELETE CASCADE, 
	CONSTRAINT fk_stock_movements_pot_id_recipe_cooking_logs FOREIGN KEY(pot_id) REFERENCES recipe_cooking_logs (id) ON DELETE SET NULL, 
	CONSTRAINT fk_stock_movements_portion_id_meal_portions FOREIGN KEY(portion_id) REFERENCES meal_portions (id) ON DELETE SET NULL, 
	CONSTRAINT fk_stock_movements_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_stock_movements_household_id ON stock_movements (household_id);
CREATE INDEX ix_stock_movements_id ON stock_movements (id);
CREATE INDEX ix_stock_movements_lot_id ON stock_movements (lot_id);
CREATE INDEX ix_stock_movements_portion_id ON stock_movements (portion_id);
CREATE INDEX ix_stock_movements_pot_id ON stock_movements (pot_id);
CREATE INDEX ix_stock_movements_product_id ON stock_movements (product_id);
CREATE TABLE shopping_lists (
	id SERIAL NOT NULL, 
	household_id INTEGER NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	closed_at TIMESTAMP WITHOUT TIME ZONE, 
	CONSTRAINT pk_shopping_lists PRIMARY KEY (id), 
	CONSTRAINT fk_shopping_lists_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);
CREATE INDEX ix_shopping_lists_household_id ON shopping_lists (household_id);
CREATE INDEX ix_shopping_lists_id ON shopping_lists (id);
CREATE TABLE shopping_lines (
	id SERIAL NOT NULL, 
	list_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	variant_id INTEGER, 
	needed NUMERIC(9, 1), 
	package_amount NUMERIC(9, 1), 
	package_count INTEGER, 
	is_extra BOOLEAN NOT NULL, 
	is_staple BOOLEAN NOT NULL, 
	is_checked BOOLEAN NOT NULL, 
	checked_by_user_id INTEGER, 
	checked_at TIMESTAMP WITHOUT TIME ZONE, 
	lot_id INTEGER, 
	CONSTRAINT pk_shopping_lines PRIMARY KEY (id), 
	CONSTRAINT fk_shopping_lines_list_id_shopping_lists FOREIGN KEY(list_id) REFERENCES shopping_lists (id) ON DELETE CASCADE, 
	CONSTRAINT fk_shopping_lines_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	CONSTRAINT fk_shopping_lines_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE SET NULL, 
	CONSTRAINT fk_shopping_lines_checked_by_user_id_users FOREIGN KEY(checked_by_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	CONSTRAINT fk_shopping_lines_lot_id_stock_lots FOREIGN KEY(lot_id) REFERENCES stock_lots (id) ON DELETE SET NULL
);
CREATE INDEX ix_shopping_lines_id ON shopping_lines (id);
CREATE INDEX ix_shopping_lines_list_id ON shopping_lines (list_id);
"""

TABLES = ['shopping_lines', 'shopping_lists', 'stock_movements', 'stock_lots', 'household_products', 'product_packages']


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("base_unit", sa.String(4), nullable=False, server_default="g"),
    )
    op.add_column("products", sa.Column("piece_weight_g", sa.Numeric(7, 1), nullable=True))
    conn = op.get_bind()
    for statement in NEW_TABLES_SQL.split(";"):
        if statement.strip():
            conn.execute(sa.text(statement))


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
    op.drop_column("products", "piece_weight_g")
    op.drop_column("products", "base_unit")

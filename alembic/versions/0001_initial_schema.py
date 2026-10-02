"""initial schema (DDL из ORM-моделей, диалект PostgreSQL)

Revision ID: 0001
Revises:
Create Date: 2026-10-03

Сгенерирована детерминированно из Base.metadata (dialect=postgresql),
а не через `--autogenerate`, т.к. на этапе разработки live-БД была недоступна.
Порядок таблиц — по зависимостям (metadata.sorted_tables).

После подключения PostgreSQL проверьте актуальность:
    alembic upgrade head
    alembic check          # "No new upgrade operations detected"
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UPGRADE_SQL = """
CREATE TABLE auth_groups (
	id SERIAL NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	permissions VARCHAR(255) NOT NULL, 
	CONSTRAINT pk_auth_groups PRIMARY KEY (id), 
	CONSTRAINT uq_auth_groups_name UNIQUE (name)
);
    CREATE INDEX ix_auth_groups_id ON auth_groups (id);
    CREATE TABLE brands (
	id SERIAL NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	search_name VARCHAR(255) NOT NULL, 
	CONSTRAINT pk_brands PRIMARY KEY (id), 
	CONSTRAINT uq_brands_search_name UNIQUE (search_name)
);
    CREATE INDEX ix_brands_id ON brands (id);
    CREATE TABLE product_categories (
	id SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	CONSTRAINT pk_product_categories PRIMARY KEY (id), 
	CONSTRAINT uq_product_categories_name UNIQUE (name)
);
    CREATE INDEX ix_product_categories_id ON product_categories (id);
    CREATE TABLE recipe_categories (
	id SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	search_name VARCHAR(100) NOT NULL, 
	CONSTRAINT pk_recipe_categories PRIMARY KEY (id), 
	CONSTRAINT uq_recipe_categories_search_name UNIQUE (search_name)
);
    CREATE INDEX ix_recipe_categories_id ON recipe_categories (id);
    CREATE TABLE users (
	id SERIAL NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	search_username VARCHAR(50) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	search_email VARCHAR(255) NOT NULL, 
	hashed_password VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_search_username UNIQUE (search_username), 
	CONSTRAINT uq_users_search_email UNIQUE (search_email)
);
    CREATE INDEX ix_users_id ON users (id);
    CREATE TABLE products (
	id SERIAL NOT NULL, 
	category_id INTEGER NOT NULL, 
	brand_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	search_name VARCHAR(255) NOT NULL, 
	is_verified BOOLEAN, 
	CONSTRAINT pk_products PRIMARY KEY (id), 
	CONSTRAINT _product_brand_search_uc UNIQUE (brand_id, search_name), 
	CONSTRAINT fk_products_category_id_product_categories FOREIGN KEY(category_id) REFERENCES product_categories (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_products_brand_id_brands FOREIGN KEY(brand_id) REFERENCES brands (id) ON DELETE RESTRICT
);
    CREATE INDEX ix_products_id ON products (id);
    CREATE TABLE recipes (
	id SERIAL NOT NULL, 
	recipe_category_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	cooking_time_minutes INTEGER, 
	instructions TEXT, 
	created_by_user VARCHAR(100) NOT NULL, 
	default_servings INTEGER NOT NULL, 
	total_raw_weight NUMERIC(6, 1) NOT NULL, 
	estimated_cooked_weight NUMERIC(6, 1) NOT NULL, 
	calories_per_100g NUMERIC(5, 1) NOT NULL, 
	proteins_per_100g NUMERIC(4, 1) NOT NULL, 
	fats_per_100g NUMERIC(4, 1) NOT NULL, 
	carbs_per_100g NUMERIC(4, 1) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	is_public BOOLEAN, 
	ai_generated BOOLEAN, 
	CONSTRAINT pk_recipes PRIMARY KEY (id), 
	CONSTRAINT fk_recipes_recipe_category_id_recipe_categories FOREIGN KEY(recipe_category_id) REFERENCES recipe_categories (id) ON DELETE RESTRICT
);
    CREATE INDEX ix_recipes_id ON recipes (id);
    CREATE TABLE user_groups (
	user_id INTEGER NOT NULL, 
	group_id INTEGER NOT NULL, 
	granted_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	CONSTRAINT pk_user_groups PRIMARY KEY (user_id, group_id), 
	CONSTRAINT fk_user_groups_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_groups_group_id_auth_groups FOREIGN KEY(group_id) REFERENCES auth_groups (id) ON DELETE CASCADE
);
    CREATE TABLE product_manufacturers (
	id SERIAL NOT NULL, 
	product_id INTEGER NOT NULL, 
	name VARCHAR(255), 
	search_name VARCHAR(255), 
	CONSTRAINT pk_product_manufacturers PRIMARY KEY (id), 
	CONSTRAINT _product_manufacturer_uc UNIQUE (product_id, search_name), 
	CONSTRAINT fk_product_manufacturers_product_id_products FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
    CREATE INDEX ix_product_manufacturers_id ON product_manufacturers (id);
    CREATE TABLE recipe_cooking_logs (
	id SERIAL NOT NULL, 
	recipe_id INTEGER, 
	user_id INTEGER NOT NULL, 
	cooked_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	total_raw_weight NUMERIC(6, 1) NOT NULL, 
	total_cooked_weight NUMERIC(6, 1) NOT NULL, 
	current_remaining_weight NUMERIC(6, 1) NOT NULL, 
	is_finished BOOLEAN NOT NULL, 
	calories_per_100g NUMERIC(5, 1) NOT NULL, 
	proteins_per_100g NUMERIC(4, 1) NOT NULL, 
	fats_per_100g NUMERIC(4, 1) NOT NULL, 
	carbs_per_100g NUMERIC(4, 1) NOT NULL, 
	household_id VARCHAR, 
	CONSTRAINT pk_recipe_cooking_logs PRIMARY KEY (id), 
	CONSTRAINT fk_recipe_cooking_logs_recipe_id_recipes FOREIGN KEY(recipe_id) REFERENCES recipes (id) ON DELETE SET NULL, 
	CONSTRAINT fk_recipe_cooking_logs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
    CREATE INDEX ix_recipe_cooking_logs_household_id ON recipe_cooking_logs (household_id);
    CREATE INDEX ix_recipe_cooking_logs_id ON recipe_cooking_logs (id);
    CREATE INDEX ix_recipe_cooking_logs_user_id ON recipe_cooking_logs (user_id);
    CREATE TABLE diary_logs (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	date_day VARCHAR(10) NOT NULL, 
	meal_type VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	recipe_id INTEGER, 
	cooking_log_id INTEGER, 
	weight_g NUMERIC(5, 1) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	scale_all_proportions BOOLEAN, 
	household_id VARCHAR, 
	servings_multiplier INTEGER, 
	CONSTRAINT pk_diary_logs PRIMARY KEY (id), 
	CONSTRAINT fk_diary_logs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_diary_logs_recipe_id_recipes FOREIGN KEY(recipe_id) REFERENCES recipes (id) ON DELETE SET NULL, 
	CONSTRAINT fk_diary_logs_cooking_log_id_recipe_cooking_logs FOREIGN KEY(cooking_log_id) REFERENCES recipe_cooking_logs (id) ON DELETE SET NULL
);
    CREATE INDEX ix_diary_logs_date_day ON diary_logs (date_day);
    CREATE INDEX ix_diary_logs_household_id ON diary_logs (household_id);
    CREATE INDEX ix_diary_logs_id ON diary_logs (id);
    CREATE INDEX ix_diary_logs_user_id ON diary_logs (user_id);
    CREATE TABLE product_variants (
	id SERIAL NOT NULL, 
	manufacturer_id INTEGER NOT NULL, 
	calories NUMERIC(5, 1) NOT NULL, 
	proteins NUMERIC(4, 1) NOT NULL, 
	fats NUMERIC(4, 1) NOT NULL, 
	carbs NUMERIC(4, 1) NOT NULL, 
	wrong_nutrients BOOLEAN NOT NULL, 
	version INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(), 
	created_by_user VARCHAR(100) NOT NULL, 
	is_rejected BOOLEAN NOT NULL, 
	is_approved BOOLEAN NOT NULL, 
	CONSTRAINT pk_product_variants PRIMARY KEY (id), 
	CONSTRAINT _manufacturer_version_uc UNIQUE (manufacturer_id, version), 
	CONSTRAINT fk_product_variants_manufacturer_id_product_manufacturers FOREIGN KEY(manufacturer_id) REFERENCES product_manufacturers (id) ON DELETE CASCADE
);
    CREATE INDEX ix_product_variants_id ON product_variants (id);
    CREATE TABLE recipe_actual_ingredients (
	id SERIAL NOT NULL, 
	cooking_log_id INTEGER NOT NULL, 
	variant_id INTEGER NOT NULL, 
	weight_g NUMERIC(5, 1) NOT NULL, 
	CONSTRAINT pk_recipe_actual_ingredients PRIMARY KEY (id), 
	CONSTRAINT fk_recipe_actual_ingredients_cooking_log_id_recipe_cooking_logs FOREIGN KEY(cooking_log_id) REFERENCES recipe_cooking_logs (id) ON DELETE CASCADE, 
	CONSTRAINT fk_recipe_actual_ingredients_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT
);
    CREATE INDEX ix_recipe_actual_ingredients_id ON recipe_actual_ingredients (id);
    CREATE TABLE recipe_template_ingredients (
	id SERIAL NOT NULL, 
	recipe_id INTEGER NOT NULL, 
	variant_id INTEGER NOT NULL, 
	weight_g NUMERIC(5, 1) NOT NULL, 
	CONSTRAINT pk_recipe_template_ingredients PRIMARY KEY (id), 
	CONSTRAINT fk_recipe_template_ingredients_recipe_id_recipes FOREIGN KEY(recipe_id) REFERENCES recipes (id) ON DELETE CASCADE, 
	CONSTRAINT fk_recipe_template_ingredients_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT
);
    CREATE INDEX ix_recipe_template_ingredients_id ON recipe_template_ingredients (id);
"""

DOWNGRADE_TABLES = ['recipe_template_ingredients', 'recipe_actual_ingredients', 'product_variants', 'diary_logs', 'recipe_cooking_logs', 'product_manufacturers', 'user_groups', 'recipes', 'products', 'users', 'recipe_categories', 'product_categories', 'brands', 'auth_groups']


def upgrade() -> None:
    for stmt in UPGRADE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(sa.text(stmt))


def downgrade() -> None:
    for name in DOWNGRADE_TABLES:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {name} CASCADE"))

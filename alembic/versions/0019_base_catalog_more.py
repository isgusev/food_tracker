"""базовый справочник, дополнение: говядина по жирности, молоко, кефир, творог, сливки разной жирности

Revision ID: 0019_base_catalog_more
Revises: 0018_base_catalog
Create Date: 2026-11-11

Те же правила, что в 0018_base_catalog: КБЖУ на 100 г сырого продукта (таблицы Скурихина;
для жирностей, которых там нет, — типичные значения с этикеток), бренд «Без бренда»,
повторный запуск и совпадение с существующими товарами безопасны.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0019_base_catalog_more"
down_revision = "0018_base_catalog"
branch_labels = None
depends_on = None

SOURCE = "base_catalog"

# (категория, название, ккал, белки, жиры, углеводы)
CATALOG: list[tuple] = [
    # --- Говядина по жирности (к «Говядине» из 0018) ---
    ("Мясо", "Говядина постная (вырезка)", 125, 20.2, 4.8, 0.0),
    ("Мясо", "Говядина 2 категории", 154, 20.0, 8.3, 0.0),
    ("Мясо", "Говядина 1 категории", 218, 18.6, 16.0, 0.0),
    ("Мясо", "Говядина жирная", 250, 17.0, 20.0, 0.0),
    ("Мясо", "Фарш говяжий", 254, 17.2, 20.0, 0.0),
    # --- Молоко ---
    ("Молочные продукты", "Молоко 0,5%", 35, 2.9, 0.5, 4.8),
    ("Молочные продукты", "Молоко 1,5%", 44, 2.8, 1.5, 4.7),
    ("Молочные продукты", "Молоко 6%", 84, 3.0, 6.0, 4.7),
    # --- Кефир ---
    ("Молочные продукты", "Кефир 0%", 30, 3.0, 0.1, 3.8),
    ("Молочные продукты", "Кефир 1%", 40, 2.8, 1.0, 4.0),
    # --- Творог ---
    ("Молочные продукты", "Творог 0%", 71, 16.5, 0.0, 1.3),
    ("Молочные продукты", "Творог 2%", 104, 18.0, 2.0, 3.3),
    ("Молочные продукты", "Творог 18%", 232, 14.0, 18.0, 2.8),
    # --- Сливки ---
    ("Молочные продукты", "Сливки 15%", 162, 2.6, 15.0, 3.6),
    ("Молочные продукты", "Сливки 20%", 205, 2.8, 20.0, 3.7),
    ("Молочные продукты", "Сливки 33%", 322, 2.2, 33.0, 3.0),
]


def upgrade() -> None:
    bind = op.get_bind()
    q = lambda sql, **kw: bind.execute(sa.text(sql), kw)  # noqa: E731

    brand = q("SELECT id FROM brands WHERE search_name = 'без бренда'").scalar()
    if brand is None:
        brand = q("INSERT INTO brands (name, search_name) VALUES ('Без бренда', 'без бренда') RETURNING id").scalar()
    # категории — без учёта регистра (как в приложении)
    categories = {name.strip().lower(): cid for cid, name in q("SELECT id, name FROM product_categories").all()}

    for row in CATALOG:
        cat, name, kcal, prot, fat, carb = row[:6]
        unit, piece, package = (row[6], row[7], row[8]) if len(row) > 6 else ("g", None, None)
        key = name.lower()
        if q("SELECT 1 FROM products WHERE brand_id = :b AND search_name = :k", b=brand, k=key).first():
            continue  # уже есть «Без бренда» с таким названием
        cid = categories.get(cat.lower())
        if cid is None:
            cid = q("INSERT INTO product_categories (name) VALUES (:n) RETURNING id", n=cat).scalar()
            categories[cat.lower()] = cid
        if q("SELECT 1 FROM items WHERE key = :k", k=key).first():
            # товар уже есть (свои бренды) — единица учёта общая для товара
            same = q("SELECT base_unit, piece_weight_g FROM products WHERE item_key = :k LIMIT 1", k=key).first()
            if same is not None:
                unit, piece = same[0], same[1]
        else:
            q("INSERT INTO items (key, name) VALUES (:k, :n)", k=key, n=name)
        pid = q(
            "INSERT INTO products (category_id, brand_id, name, search_name, item_key, is_verified, base_unit, piece_weight_g, kbju_missing)"
            " VALUES (:c, :b, :n, :k, :k, true, :u, :pw, false) RETURNING id",
            c=cid, b=brand, n=name, k=key, u=unit, pw=piece,
        ).scalar()
        mid = q("INSERT INTO product_manufacturers (product_id, name, search_name) VALUES (:p, NULL, NULL) RETURNING id", p=pid).scalar()
        q(
            "INSERT INTO product_variants (manufacturer_id, calories, proteins, fats, carbs, wrong_nutrients, version,"
            " is_active, created_by_user, is_rejected, is_approved)"
            " VALUES (:m, :k, :p, :f, :c, false, 1, true, :src, false, true)",
            m=mid, k=kcal, p=prot, f=fat, c=carb, src=SOURCE,
        )
        if package and unit == "pcs":
            q("INSERT INTO product_packages (product_id, amount, name) VALUES (:p, :a, 'упаковка')", p=pid, a=package)


def downgrade() -> None:
    """Убрать продукты этой миграции, которыми никто не пользовался."""
    bind = op.get_bind()
    names = [row[1].lower() for row in CATALOG]
    bind.execute(sa.text(
        """
        DELETE FROM products p
        WHERE p.search_name = ANY(:names)
        AND p.brand_id = (SELECT id FROM brands WHERE search_name = 'без бренда')
        AND p.id IN (
            SELECT m.product_id FROM product_manufacturers m
            JOIN product_variants v ON v.manufacturer_id = m.id
            WHERE v.created_by_user = :src
        )
        AND NOT EXISTS (SELECT 1 FROM stock_lots l WHERE l.product_id = p.id)
        AND NOT EXISTS (SELECT 1 FROM shopping_lines s WHERE s.product_id = p.id)
        AND NOT EXISTS (
            SELECT 1 FROM product_manufacturers m JOIN product_variants v ON v.manufacturer_id = m.id
            WHERE m.product_id = p.id AND (
                EXISTS (SELECT 1 FROM recipe_template_ingredients r WHERE r.variant_id = v.id)
                OR EXISTS (SELECT 1 FROM recipe_actual_ingredients a WHERE a.variant_id = v.id)
                OR EXISTS (SELECT 1 FROM meal_items i WHERE i.variant_id = v.id)
            )
        )
        """
    ), {"src": SOURCE, "names": names})
    bind.execute(sa.text("DELETE FROM items i WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.item_key = i.key)"))

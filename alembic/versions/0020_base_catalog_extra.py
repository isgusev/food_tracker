"""базовый справочник, дополнение 2: сметана, свинина, птица, овощи, фрукты, ягоды, орехи, крупы, рыба

Состав: сметана 10/15/25%, свинина по частям туши и фарши, птица и субпродукты, овощи и зелень,
фрукты, ягоды, сухофрукты, орехи и семечки, крупы и мука, перепелиные яйца, рыба и морепродукты.

Revision ID: 0020_base_catalog_extra
Revises: 0019_base_catalog_more
Create Date: 2026-11-11

Те же правила, что в 0018_base_catalog: КБЖУ на 100 г сырого съедобного продукта
(таблицы Скурихина; чего там нет — типичные значения с этикеток), бренд «Без бренда»,
повторный запуск и совпадение с существующими товарами безопасны.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0020_base_catalog_extra"
down_revision = "0019_base_catalog_more"
branch_labels = None
depends_on = None

SOURCE = "base_catalog"

# (категория, название, ккал, белки, жиры, углеводы[, единица, вес штуки г, упаковка])
CATALOG: list[tuple] = [
    # --- Сметана ---
    ("Молочные продукты", "Сметана 10%", 115, 3.0, 10.0, 2.9),
    ("Молочные продукты", "Сметана 15%", 158, 2.6, 15.0, 3.0),
    ("Молочные продукты", "Сметана 25%", 248, 2.6, 25.0, 2.5),
    # --- Прочая молочка ---
    ("Молочные продукты", "Ряженка 4%", 67, 2.8, 4.0, 4.2),
    ("Молочные продукты", "Йогурт натуральный 3,2%", 66, 5.0, 3.2, 3.5),
    ("Масла и жиры", "Масло сливочное 72,5%", 661, 0.8, 72.5, 1.3),
    # --- Свинина по частям туши ---
    ("Мясо", "Свиная корейка", 181, 19.4, 11.5, 0.0),
    ("Мясо", "Свиная шея", 267, 13.8, 23.5, 0.0),
    ("Мясо", "Свиная лопатка", 241, 16.8, 19.3, 0.0),
    ("Мясо", "Свиной окорок", 230, 16.9, 18.0, 0.0),
    ("Мясо", "Свиная грудинка", 518, 7.6, 53.0, 0.0),
    ("Мясо", "Фарш свиной", 263, 17.0, 21.2, 0.0),
    ("Мясо", "Фарш свино-говяжий", 262, 17.2, 20.9, 0.0),
    ("Масла и жиры", "Сало свиное", 797, 1.4, 89.0, 0.0),
    # --- Птица и субпродукты ---
    ("Птица", "Куриные голени", 161, 18.1, 9.2, 0.0),
    ("Птица", "Куриные крылья", 186, 18.3, 12.1, 0.0),
    ("Птица", "Куриные сердечки", 159, 15.8, 10.3, 0.8),
    ("Птица", "Куриные желудки", 94, 17.6, 2.4, 0.0),
    ("Птица", "Бедро индейки", 144, 19.0, 7.5, 0.0),
    ("Мясо", "Печень говяжья", 127, 17.9, 3.7, 5.3),
    ("Мясо", "Язык говяжий", 146, 12.2, 10.9, 0.0),
    # --- Овощи и зелень ---
    ("Овощи", "Капуста пекинская", 16, 1.2, 0.2, 2.0),
    ("Овощи", "Фасоль стручковая", 24, 2.0, 0.2, 3.6),
    ("Овощи", "Батат", 86, 1.6, 0.1, 18.2),
    ("Овощи", "Спаржа", 20, 1.9, 0.1, 3.1),
    ("Овощи", "Лук-порей", 33, 2.0, 0.0, 6.5),
    ("Овощи", "Руккола", 25, 2.6, 0.7, 2.1),
    ("Овощи", "Базилик", 23, 3.2, 0.6, 1.0),
    ("Овощи", "Кинза", 23, 2.1, 0.5, 1.9),
    ("Грибы", "Вешенки", 33, 3.3, 0.4, 3.4),
    # --- Фрукты ---
    ("Фрукты и ягоды", "Персики", 45, 0.9, 0.1, 9.5),
    ("Фрукты и ягоды", "Сливы", 49, 0.8, 0.3, 9.6),
    ("Фрукты и ягоды", "Абрикосы", 44, 0.9, 0.1, 9.0),
    ("Фрукты и ягоды", "Грейпфрут", 35, 0.7, 0.2, 6.5),
    ("Фрукты и ягоды", "Ананас", 52, 0.4, 0.2, 11.5),
    ("Фрукты и ягоды", "Арбуз", 27, 0.6, 0.1, 5.8),
    ("Фрукты и ягоды", "Дыня", 35, 0.6, 0.3, 7.4),
    ("Фрукты и ягоды", "Хурма", 67, 0.5, 0.4, 15.3),
    # --- Ягоды ---
    ("Фрукты и ягоды", "Малина", 46, 0.8, 0.5, 8.3),
    ("Фрукты и ягоды", "Черника", 44, 1.1, 0.4, 7.6),
    ("Фрукты и ягоды", "Смородина чёрная", 44, 1.0, 0.4, 7.3),
    ("Фрукты и ягоды", "Вишня", 52, 0.8, 0.2, 10.6),
    ("Фрукты и ягоды", "Клюква", 28, 0.5, 0.2, 3.7),
    # --- Сухофрукты ---
    ("Сухофрукты", "Изюм", 264, 2.9, 0.6, 66.0),
    ("Сухофрукты", "Курага", 232, 5.2, 0.3, 51.0),
    ("Сухофрукты", "Чернослив", 231, 2.3, 0.7, 57.5),
    ("Сухофрукты", "Финики", 274, 2.5, 0.5, 69.2),
    # --- Орехи и семечки ---
    ("Орехи", "Фундук", 704, 16.1, 66.9, 9.9),
    ("Орехи", "Кешью", 600, 18.5, 48.5, 22.5),
    ("Орехи", "Арахис", 551, 26.3, 45.2, 9.9),
    ("Орехи", "Семечки подсолнечника", 578, 20.7, 52.9, 3.4),
    ("Орехи", "Кунжут", 565, 19.4, 48.7, 12.2),
    # --- Крупы и бобовые ---
    ("Крупы и бобовые", "Рис бурый", 337, 7.4, 1.8, 72.9),
    ("Крупы и бобовые", "Булгур", 345, 12.3, 1.3, 70.6),
    ("Крупы и бобовые", "Киноа", 368, 14.1, 6.1, 57.2),
    ("Крупы и бобовые", "Кукурузная крупа", 337, 8.3, 1.2, 71.0),
    ("Крупы и бобовые", "Ячневая крупа", 313, 10.0, 1.3, 65.4),
    ("Крупы и бобовые", "Нут", 364, 19.0, 6.0, 61.0),
    ("Макароны и мука", "Мука ржаная", 298, 10.7, 1.9, 58.5),
    ("Макароны и мука", "Крахмал картофельный", 313, 0.1, 0.0, 78.2),
    # --- Яйца: в штуках (1 шт ≈ 12 г), упаковка — 20 шт ---
    ("Яйца", "Яйца перепелиные", 168, 11.9, 13.1, 0.6, "pcs", 12, 20),
    # --- Рыба и морепродукты ---
    ("Рыба и морепродукты", "Судак", 84, 18.4, 1.1, 0.0),
    ("Рыба и морепродукты", "Карп", 112, 16.0, 5.3, 0.0),
    ("Рыба и морепродукты", "Форель", 97, 19.2, 2.1, 0.0),
    ("Рыба и морепродукты", "Камбала", 83, 15.7, 3.0, 0.0),
    ("Рыба и морепродукты", "Пикша", 71, 17.2, 0.5, 0.0),
    ("Рыба и морепродукты", "Тунец", 101, 23.0, 1.0, 0.0),
    ("Рыба и морепродукты", "Мидии", 77, 11.5, 2.0, 3.3),
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

"""семьи: households/household_members, план семьи meal_items/meal_portions вместо diary_logs

Revision ID: 0006_households
Revises: 0005_date_and_weights
Create Date: 2026-10-07

Перенос данных:
- каждому пользователю — своя семья (имя «Семья <username>») и член семьи;
- рецепты и кастрюли получают household_id своего автора;
- каждая запись diary_logs → блюдо плана с порцией пользователя; если
  servings_multiplier > 1, остальные едоки становятся порциями-гостями
  (member_id = NULL) того же веса — как раньше их и считали кастрюля/покупки.

Downgrade обратный, но с потерями: порции членов семьи без аккаунта не
переносятся, гости сворачиваются обратно в servings_multiplier.
"""
from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_households"
down_revision = "0005_date_and_weights"
branch_labels = None
depends_on = None

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

NEW_TABLES_SQL = """
CREATE TABLE households (
    id SERIAL NOT NULL,
    name VARCHAR(100) NOT NULL,
    invite_code VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    CONSTRAINT pk_households PRIMARY KEY (id),
    CONSTRAINT uq_households_invite_code UNIQUE (invite_code)
);
CREATE INDEX ix_households_id ON households (id);

CREATE TABLE household_members (
    id SERIAL NOT NULL,
    household_id INTEGER NOT NULL,
    user_id INTEGER,
    name VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL,
    target_calories NUMERIC(6, 1),
    target_proteins NUMERIC(5, 1),
    target_fats NUMERIC(5, 1),
    target_carbs NUMERIC(5, 1),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    CONSTRAINT pk_household_members PRIMARY KEY (id),
    CONSTRAINT fk_household_members_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE,
    CONSTRAINT uq_household_members_user_id UNIQUE (user_id),
    CONSTRAINT fk_household_members_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_household_members_household_id ON household_members (household_id);
CREATE INDEX ix_household_members_id ON household_members (id);

CREATE TABLE meal_items (
    id SERIAL NOT NULL,
    household_id INTEGER NOT NULL,
    date_day DATE NOT NULL,
    meal_type VARCHAR(20) NOT NULL,
    recipe_id INTEGER,
    variant_id INTEGER,
    cooking_log_id INTEGER,
    created_by_user_id INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    CONSTRAINT pk_meal_items PRIMARY KEY (id),
    CONSTRAINT fk_meal_items_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_items_recipe_id_recipes FOREIGN KEY(recipe_id) REFERENCES recipes (id) ON DELETE SET NULL,
    CONSTRAINT fk_meal_items_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT,
    CONSTRAINT fk_meal_items_cooking_log_id_recipe_cooking_logs FOREIGN KEY(cooking_log_id) REFERENCES recipe_cooking_logs (id) ON DELETE SET NULL,
    CONSTRAINT fk_meal_items_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_meal_items_cooking_log_id ON meal_items (cooking_log_id);
CREATE INDEX ix_meal_items_date_day ON meal_items (date_day);
CREATE INDEX ix_meal_items_household_id ON meal_items (household_id);
CREATE INDEX ix_meal_items_id ON meal_items (id);

CREATE TABLE meal_portions (
    id SERIAL NOT NULL,
    meal_item_id INTEGER NOT NULL,
    member_id INTEGER,
    weight_g NUMERIC(6, 1) NOT NULL,
    is_eaten BOOLEAN NOT NULL,
    eaten_from_pot_id INTEGER,
    eaten_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT pk_meal_portions PRIMARY KEY (id),
    CONSTRAINT fk_meal_portions_meal_item_id_meal_items FOREIGN KEY(meal_item_id) REFERENCES meal_items (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_portions_member_id_household_members FOREIGN KEY(member_id) REFERENCES household_members (id) ON DELETE SET NULL,
    CONSTRAINT fk_meal_portions_eaten_from_pot_id_recipe_cooking_logs FOREIGN KEY(eaten_from_pot_id) REFERENCES recipe_cooking_logs (id) ON DELETE SET NULL
);
CREATE INDEX ix_meal_portions_eaten_from_pot_id ON meal_portions (eaten_from_pot_id);
CREATE INDEX ix_meal_portions_id ON meal_portions (id);
CREATE INDEX ix_meal_portions_meal_item_id ON meal_portions (meal_item_id);
CREATE INDEX ix_meal_portions_member_id ON meal_portions (member_id);
"""

MIGRATE_DIARY_SQL = """
ALTER TABLE meal_items ADD COLUMN tmp_log_id INTEGER;

INSERT INTO meal_items (household_id, date_day, meal_type, recipe_id, variant_id,
                        cooking_log_id, created_by_user_id, created_at, tmp_log_id)
SELECT m.household_id, d.date_day, d.meal_type, d.recipe_id, d.variant_id,
       CASE WHEN d.status IN ('cooked_plan', 'fact') THEN d.cooking_log_id END,
       d.user_id, d.created_at, d.id
FROM diary_logs d
JOIN household_members m ON m.user_id = d.user_id;

-- порция самого пользователя
INSERT INTO meal_portions (meal_item_id, member_id, weight_g, is_eaten, eaten_from_pot_id, eaten_at)
SELECT i.id, m.id, d.weight_g, d.status = 'fact',
       CASE WHEN d.status = 'fact' THEN d.cooking_log_id END,
       CASE WHEN d.status = 'fact' THEN d.updated_at END
FROM meal_items i
JOIN diary_logs d ON d.id = i.tmp_log_id
JOIN household_members m ON m.user_id = d.user_id;

-- остальные «едоки» записи — порции-гости того же веса
INSERT INTO meal_portions (meal_item_id, member_id, weight_g, is_eaten, eaten_from_pot_id, eaten_at)
SELECT i.id, NULL, d.weight_g, d.status = 'fact',
       CASE WHEN d.status = 'fact' THEN d.cooking_log_id END,
       CASE WHEN d.status = 'fact' THEN d.updated_at END
FROM meal_items i
JOIN diary_logs d ON d.id = i.tmp_log_id
CROSS JOIN LATERAL generate_series(2, GREATEST(ABS(COALESCE(d.servings_multiplier, 1)), 1)) AS g(n);

ALTER TABLE meal_items DROP COLUMN tmp_log_id;
DROP TABLE diary_logs;
"""


def _run(conn, script: str) -> None:
    """Выполнить SQL-скрипт по одному оператору (строки-комментарии отбрасываются)."""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    for statement in "\n".join(lines).split(";"):
        if statement.strip():
            conn.execute(sa.text(statement))


def _code(taken: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        if code not in taken:
            taken.add(code)
            return code


def upgrade() -> None:
    conn = op.get_bind()
    _run(conn, NEW_TABLES_SQL)

    # семья и член семьи на каждого пользователя
    taken: set[str] = set()
    for user_id, username in conn.execute(sa.text("SELECT id, username FROM users ORDER BY id")).all():
        household_id = conn.execute(
            sa.text("INSERT INTO households (name, invite_code) VALUES (:n, :c) RETURNING id"),
            {"n": f"Семья {username}"[:100], "c": _code(taken)},
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO household_members (household_id, user_id, name, is_active) "
                "VALUES (:h, :u, :n, true)"
            ),
            {"h": household_id, "u": user_id, "n": username[:50]},
        )

    # рецепты: household_id автора
    op.add_column("recipes", sa.Column("household_id", sa.Integer(), nullable=True))
    conn.execute(sa.text(
        "UPDATE recipes r SET household_id = m.household_id "
        "FROM household_members m WHERE m.user_id = r.user_id"
    ))
    op.alter_column("recipes", "household_id", nullable=False)
    op.create_foreign_key(
        "fk_recipes_household_id_households", "recipes", "households",
        ["household_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_recipes_household_id", "recipes", ["household_id"])

    # кастрюли: прежний «задел» household_id (строка, всегда NULL) → настоящий FK
    op.drop_index("ix_recipe_cooking_logs_household_id", table_name="recipe_cooking_logs")
    op.drop_column("recipe_cooking_logs", "household_id")
    op.add_column("recipe_cooking_logs", sa.Column("household_id", sa.Integer(), nullable=True))
    conn.execute(sa.text(
        "UPDATE recipe_cooking_logs p SET household_id = m.household_id "
        "FROM household_members m WHERE m.user_id = p.user_id"
    ))
    op.alter_column("recipe_cooking_logs", "household_id", nullable=False)
    op.create_foreign_key(
        "fk_recipe_cooking_logs_household_id_households", "recipe_cooking_logs", "households",
        ["household_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_recipe_cooking_logs_household_id", "recipe_cooking_logs", ["household_id"])

    _run(conn, MIGRATE_DIARY_SQL)


DIARY_TABLE_SQL = """
CREATE TABLE diary_logs (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    date_day DATE NOT NULL,
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
    variant_id INTEGER,
    CONSTRAINT pk_diary_logs PRIMARY KEY (id),
    CONSTRAINT fk_diary_logs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_diary_logs_recipe_id_recipes FOREIGN KEY(recipe_id) REFERENCES recipes (id) ON DELETE SET NULL,
    CONSTRAINT fk_diary_logs_cooking_log_id_recipe_cooking_logs FOREIGN KEY(cooking_log_id) REFERENCES recipe_cooking_logs (id) ON DELETE SET NULL,
    CONSTRAINT fk_diary_logs_variant_id_product_variants FOREIGN KEY(variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT
);
CREATE INDEX ix_diary_logs_date_day ON diary_logs (date_day);
CREATE INDEX ix_diary_logs_household_id ON diary_logs (household_id);
CREATE INDEX ix_diary_logs_id ON diary_logs (id);
CREATE INDEX ix_diary_logs_user_id ON diary_logs (user_id);

INSERT INTO diary_logs (user_id, date_day, meal_type, status, recipe_id, cooking_log_id,
                        weight_g, created_at, updated_at, scale_all_proportions,
                        servings_multiplier, variant_id)
SELECT m.user_id, i.date_day, i.meal_type,
       CASE WHEN p.is_eaten THEN 'fact'
            WHEN i.cooking_log_id IS NOT NULL THEN 'cooked_plan'
            ELSE 'template_plan' END,
       i.recipe_id,
       CASE WHEN p.is_eaten THEN p.eaten_from_pot_id ELSE i.cooking_log_id END,
       LEAST(p.weight_g, 999.9), i.created_at, COALESCE(p.eaten_at, i.created_at), false,
       LEAST(10, 1 + (SELECT COUNT(*) FROM meal_portions g
                      WHERE g.meal_item_id = i.id AND g.member_id IS NULL)),
       i.variant_id
FROM meal_portions p
JOIN meal_items i ON i.id = p.meal_item_id
JOIN household_members m ON m.id = p.member_id
WHERE m.user_id IS NOT NULL;
"""


def downgrade() -> None:
    conn = op.get_bind()
    _run(conn, DIARY_TABLE_SQL)
    op.drop_table("meal_portions")
    op.drop_table("meal_items")

    op.drop_index("ix_recipe_cooking_logs_household_id", table_name="recipe_cooking_logs")
    op.drop_constraint("fk_recipe_cooking_logs_household_id_households", "recipe_cooking_logs", type_="foreignkey")
    op.drop_column("recipe_cooking_logs", "household_id")
    op.add_column("recipe_cooking_logs", sa.Column("household_id", sa.String(), nullable=True))
    op.create_index("ix_recipe_cooking_logs_household_id", "recipe_cooking_logs", ["household_id"])

    op.drop_index("ix_recipes_household_id", table_name="recipes")
    op.drop_constraint("fk_recipes_household_id_households", "recipes", type_="foreignkey")
    op.drop_column("recipes", "household_id")

    op.drop_table("household_members")
    op.drop_table("households")

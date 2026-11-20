"""Импорт рецептов из YAML (docs/RECIPE_IMPORT.md): отчёт без записи, сопоставление ингредиентов,
выбор для несопоставленных, повторный импорт, продукты без КБЖУ, ошибки по каждому рецепту."""
from __future__ import annotations


import pytest

from app.services.recipe_import import norm, similarity
from tests.helpers import register_and_login

pytestmark = pytest.mark.anyio

FILE = """
- name: Сырники
  category: Завтраки
  servings: 4
  cooked_weight: 600
  time: 30
  effort: easy
  meal_types: [breakfast]
  keeps_days: 3
  freezable: true
  allow_half: true
  ingredients:
    - {product: Творог 5%, amount: 400, unit: г}
    - {product: Яйцо куриное, amount: 1, unit: шт, grams: 55}
    - {product: Сахар, amount: 20, unit: г}
    - {product: Масло подсолнечное, amount: 20, unit: мл, grams: 18}
    - {product: Ванилин, amount: 1, unit: г}
    - {product: Соль, to_taste: true}
  steps: |
    1. Смешать.
    2. Обжарить.
  source: https://example.org/syrniki
- name: Омлет
  category: завтраки
  servings: 1
  ingredients:
    - {product: Яйцо куриное, amount: 3, unit: шт, grams: 165}
    - {product: Молоко 3.2%, amount: 50, unit: мл}
- name: Сломанный
  category: Ужины
  ingredients:
    - {product: Мука, amount: 2, unit: ст.л.}
"""


async def product(client, h, name, brand="Без бренда", kcal=100, *, kbju=True, category="Разное") -> dict:
    body = {"category_name": category, "name": name, "brand_name": brand}
    if kbju:
        body["base_variant"] = {"manufacturer_name": brand, "calories": kcal, "proteins": 5, "fats": 5, "carbs": 5}
    r = await client.post("/api/v1/products/with-category", headers=h, json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    p["variant_id"] = p["manufacturers"][0]["variants"][0]["id"]
    return p


async def run(client, h, content=FILE, **kw) -> dict:
    r = await client.post("/api/v1/recipes/import", headers=h, json={"content": content, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_similarity():
    assert similarity(norm("Яйцо куриное"), norm("Яйца куриные")) >= 0.85
    assert similarity(norm("Творог 5%"), norm("Творог 9%")) == 0
    assert similarity(norm("Молоко 3.2%"), norm("Молоко 3,2%")) == 1
    assert 0.6 <= similarity(norm("Сахар"), norm("Сахар-песок")) < 0.85


async def test_import_dry_run_choices_and_reimport(client):
    h = await register_and_login(client, "imp", "imp@example.com")
    tvorog = await product(client, h, "Творог 5%", kcal=120)
    await product(client, h, "Творог 5%", "Простоквашино", kcal=125)
    await product(client, h, "Творог 9%", kcal=160)
    eggs = await product(client, h, "Яйца куриные", kcal=157)
    sugar = await product(client, h, "Сахар-песок", kcal=399)
    oil = await product(client, h, "Масло подсолнечное", kcal=899)
    milk = await product(client, h, "Молоко 3,2%", kcal=60)

    rep = await run(client, h)
    assert rep["dry_run"] and rep["created"] == 0
    ing = {i["product"]: i for i in rep["ingredients"]}
    assert "Соль" not in ing                                         # «по вкусу» — не в составе
    assert ing["Творог 5%"]["status"] == "matched" and ing["Творог 5%"]["pick"]["variant_id"] == tvorog["variant_id"]
    assert ing["Яйцо куриное"]["status"] == "fuzzy" and ing["Яйцо куриное"]["pick"]["variant_id"] == eggs["variant_id"]
    assert ing["Яйцо куриное"]["recipes"] == [1, 2]
    assert ing["Сахар"]["status"] == "ambiguous" and ing["Сахар"]["pick"] is None
    assert ing["Сахар"]["candidates"][0]["variant_id"] == sugar["variant_id"]
    assert ing["Ванилин"]["status"] == "missing"
    assert ing["Молоко 3.2%"]["status"] == "matched"
    rec = {r["number"]: r for r in rep["recipes"]}
    assert rec[1]["status"] == "waiting" and "Сахар" in rec[1]["errors"][0] and "Ванилин" in rec[1]["errors"][0]
    assert rec[1]["new_category"] is True
    assert rec[2]["status"] == "create" and rec[2]["cooked_weight"] == "215.0"
    assert any("1 мл = 1 г" in w for w in rec[2]["warnings"])
    assert rec[3]["status"] == "error"
    assert any("servings" in e for e in rec[3]["errors"]) and any("ст.л." not in e and "unit" in e for e in rec[3]["errors"])
    assert not (await client.get("/api/v1/recipes/", headers=h)).json()          # dry run ничего не записал

    choices = {ing["Сахар"]["key"]: sugar["variant_id"], ing["Ванилин"]["key"]: None}
    rep = await run(client, h, dry_run=False, choices=choices)
    assert rep["created"] == 2
    rec = {r["number"]: r for r in rep["recipes"]}
    assert rec[1]["status"] == "created" and any("Ванилин" in w for w in rec[1]["warnings"])
    assert rec[3]["status"] == "error"
    recipes = {r["name"]: r for r in (await client.get("/api/v1/recipes/", headers=h)).json()}
    s = recipes["Сырники"]
    assert (s["default_servings"], s["keeps_days"], s["is_freezable"], s["allow_half"]) == (4, 3, True, True)
    assert s["meal_types"] == ["breakfast"] and s["cooking_time_minutes"] == 30 and s["created_by_user"] == "import"
    assert float(s["estimated_cooked_weight"]) == 600
    assert "По вкусу: Соль." in s["instructions"] and "Источник: https://example.org/syrniki" in s["instructions"]
    weights = {i["variant_id"]: float(i["weight_g"]) for i in s["template_ingredients"]}
    assert weights == {tvorog["variant_id"]: 400, eggs["variant_id"]: 55, sugar["variant_id"]: 20, oil["variant_id"]: 18}
    # (400·120 + 55·157 + 20·399 + 18·899) / 100 → на 600 г
    assert float(s["calories_per_100g"]) == pytest.approx((480 + 86.35 + 79.8 + 161.82) / 6, abs=0.1)
    o = recipes["Омлет"]
    assert {i["variant_id"] for i in o["template_ingredients"]} == {eggs["variant_id"], milk["variant_id"]}
    assert o["recipe_category_id"] == s["recipe_category_id"]     # «завтраки» = «Завтраки»

    # повторно: уже есть — пропуск; отмеченный — обновление
    changed = FILE.replace("servings: 1\n", "servings: 2\n")
    rep = await run(client, h, changed, choices=choices)
    rec = {r["number"]: r for r in rep["recipes"]}
    assert rec[1]["status"] == rec[2]["status"] == "exists"
    rep = await run(client, h, changed, dry_run=False, choices=choices, update=[2])
    rec = {r["number"]: r for r in rep["recipes"]}
    assert (rec[1]["status"], rec[2]["status"], rep["updated"]) == ("skipped", "updated", 1)
    recipes = (await client.get("/api/v1/recipes/", headers=h)).json()
    assert len(recipes) == 2 and next(r for r in recipes if r["name"] == "Омлет")["default_servings"] == 2


async def test_import_brand_exact_pieces_and_missing_kbju(client):
    h = await register_and_login(client, "imp2", "imp2@example.com")
    await product(client, h, "Творог 5%", kcal=120)
    brand = await product(client, h, "Творог 5%", "Простоквашино", kcal=125)
    await product(client, h, "Шпинат", kbju=False)
    lemon = await product(client, h, "Лимон", kcal=30)
    r = await client.put(f"/api/v1/products/{lemon['id']}/unit", headers=h, json={"base_unit": "pcs", "piece_weight_g": 120})
    assert r.status_code == 200, r.text

    content = """
- name: Запеканка
  category: Завтраки
  servings: 2
  ingredients:
    - {product: Творог 5%, brand: Простоквашино, exact: true, amount: 200, unit: г}
    - {product: Лимон, amount: 0.5, unit: шт}
- name: Со шпинатом
  category: Завтраки
  servings: 2
  ingredients:
    - {product: Шпинат, amount: 100, unit: г}
- name: Другой бренд
  category: Завтраки
  servings: 2
  ingredients:
    - {product: Творог 5%, brand: Нет такого, exact: true, amount: 200, unit: г}
"""
    rep = await run(client, h, content)
    rec = {r["number"]: r for r in rep["recipes"]}
    assert rec[1]["status"] == "create" and any("120" in w for w in rec[1]["warnings"])
    assert rec[2]["status"] == "waiting" and "нет КБЖУ" in rec[2]["errors"][0]
    assert rec[3]["status"] == "waiting"
    ing = {(i["product"], i["brand"]): i for i in rep["ingredients"]}
    assert ing[("Творог 5%", "Простоквашино")]["pick"]["variant_id"] == brand["variant_id"]
    assert ing[("Творог 5%", "Нет такого")]["status"] == "ambiguous"

    rep = await run(client, h, content, dry_run=False)
    assert rep["created"] == 1
    z = (await client.get("/api/v1/recipes/", headers=h)).json()[0]
    lines = {i["variant_id"]: i for i in z["template_ingredients"]}
    assert lines[brand["variant_id"]]["exact"] is True
    assert float(lines[lemon["variant_id"]]["weight_g"]) == 60


async def test_import_bad_files(client):
    h = await register_and_login(client, "imp3", "imp3@example.com")
    r = await client.post("/api/v1/recipes/import", headers=h, json={"content": "- name: [x\n  servings: 1"})
    assert r.status_code == 400 and "YAML" in r.text
    r = await client.post("/api/v1/recipes/import", headers=h, json={"content": "name: Борщ"})
    assert r.status_code == 400 and "список рецептов" in r.text
    rep = await run(client, h, """
- name: Без граммов
  category: Обеды
  servings: 1
  ingredients:
    - {product: Неведомое, amount: 2, unit: шт}
- name: Без граммов
  category: Обеды
  servings: 1
  ingredients: []
""")
    rec = {r["number"]: r for r in rep["recipes"]}
    assert rec[1]["status"] == "waiting"                     # сначала — выбрать продукт
    assert rec[2]["status"] == "error" and any("№1" in e for e in rec[2]["errors"])

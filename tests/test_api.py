"""Интеграционные API-тесты: весь стек (ASGI + in-memory SQLite).

Проверяют критично важные инварианты:
- аутентификация (регистрация/логин/JWT) и защита эндпоинтов;
- изоляция пользователей в дневнике питания;
- доменная валидация КБЖУ через HTTP.
"""
from __future__ import annotations


import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def register_and_login(client: AsyncClient, username: str, email: str) -> dict:
    """Хелпер: создать пользователя и получить Bearer-заголовки."""
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/auth/token", data={"username": username, "password": "secret123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- АУТЕНТИФИКАЦИЯ ---


async def test_register_duplicate_username_conflict(client):
    body = {"username": "dupuser", "email": "a@b.com", "password": "secret123"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    r = await client.post("/api/v1/auth/register", json={**body, "email": "c@d.com"})
    assert r.status_code == 409


async def test_login_wrong_password_401(client):
    await client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "alice@test.com", "password": "secret123"},
    )
    r = await client.post("/api/v1/auth/token", data={"username": "alice", "password": "WRONG"})
    assert r.status_code == 401


async def test_me_requires_token(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    headers = await register_and_login(client, "bob", "bob@test.com")
    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "bob"


async def test_invalid_token_rejected(client):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


# --- КАТАЛОГ ПРОДУКТОВ ---


async def test_products_require_auth(client):
    assert (await client.get("/api/v1/products/")).status_code == 401


async def test_create_product_with_variant(client):
    headers = await register_and_login(client, "carol", "carol@test.com")
    r = await client.post("/api/v1/products/categories", json={"name": "Мясо"}, headers=headers)
    assert r.status_code == 201, r.text
    category_id = r.json()["id"]

    r = await client.post(
        "/api/v1/products/",
        json={
            "name": "Куриное филе",
            "category_id": category_id,
            "brand_name": "Петелинка",
            "base_variant": {
                "manufacturer_name": "Петелинка",
                "calories": 115,
                "proteins": 23.0,
                "fats": 1.9,
                "carbs": 0.0,
            },
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    variant = r.json()["manufacturers"][0]["variants"][0]
    assert float(variant["calories"]) == 115


async def test_inconsistent_nutrients_flagged(client):
    """КБЖУ не сходится по Атвотеру (4П+9Ж+4У vs ккал) → вариант помечен wrong_nutrients."""
    headers = await register_and_login(client, "dave", "dave@test.com")
    r = await client.post("/api/v1/products/categories", json={"name": "Тест"}, headers=headers)
    category_id = r.json()["id"]
    r = await client.post(
        "/api/v1/products/",
        json={
            "name": "Странный продукт",
            "category_id": category_id,
            "brand_name": "Фабрика",
            "base_variant": {
                "manufacturer_name": "Фабрика",
                "calories": 100,
                "proteins": 10,
                "fats": 5,
                "carbs": 50,
            },
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    variant = r.json()["manufacturers"][0]["variants"][0]
    assert variant["wrong_nutrients"] is True


# --- ДНЕВНИК: ИЗОЛЯЦИЯ ПОЛЬЗОВАТЕЛЕЙ + СЦЕНАРИЙ «ПЛАН → ПРИГОТОВИЛ → СЪЕЛ» ---


async def build_recipe_stack(client, headers) -> tuple[int, int]:
    """Создаёт продукт с КБЖУ (product + base_variant одним запросом) и рецепт.

    Возвращает (variant_id, recipe_id).
    """
    r = await client.post("/api/v1/products/categories", json={"name": "Бакалея"}, headers=headers)
    cat_id = r.json()["id"]
    r = await client.post(
        "/api/v1/products/",
        json={
            "name": "Овсянка",
            "category_id": cat_id,
            "brand_name": "Домашняя",
            "base_variant": {
                "manufacturer_name": "Домашняя",
                "calories": 380,
                "proteins": 12.0,
                "fats": 6.0,
                "carbs": 70.0,
            },
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    variant_id = r.json()["manufacturers"][0]["variants"][0]["id"]

    r = await client.post("/api/v1/recipes/categories", json={"name": "Завтраки"}, headers=headers)
    rcat_id = r.json()["id"]
    r = await client.post(
        "/api/v1/recipes/",
        json={
            "name": "Каша овсяная",
            "recipe_category_id": rcat_id,
            "estimated_cooked_weight": 300,
            "ingredients": [{"variant_id": variant_id, "weight_g": 60}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return variant_id, r.json()["id"]


async def test_diary_isolated_between_users(client):
    anna = await register_and_login(client, "anna", "anna@test.com")
    boris = await register_and_login(client, "boris", "boris@test.com")
    _, recipe_id = await build_recipe_stack(client, anna)

    r = await client.post(
        "/api/v1/diary/",
        json={
            "date_day": "2026-10-02",
            "meal_type": "lunch",
            "recipe_id": recipe_id,
            "weight_g": 200,
        },
        headers=anna,
    )
    assert r.status_code == 201, r.text
    log_id = r.json()["id"]
    assert r.json()["status"] == "template_plan"

    # свой день виден владельцу
    r = await client.get("/api/v1/diary/day/2026-10-02", headers=anna)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [log_id]

    # чужой день пуст; чужая запись недоступна (404 без утечки существования)
    r = await client.get("/api/v1/diary/day/2026-10-02", headers=boris)
    assert r.json() == []
    r = await client.patch(f"/api/v1/diary/{log_id}/weight", json={"weight_g": 50}, headers=boris)
    assert r.status_code == 404


async def test_full_flow_plan_cook_eaten_pot_accounting(client):
    """План → готовка (кастрюля) → «съедено»: статусы и остаток кастрюли сходятся."""
    headers = await register_and_login(client, "vera", "vera@test.com")
    _, recipe_id = await build_recipe_stack(client, headers)

    # 1. план на день
    r = await client.post(
        "/api/v1/diary/",
        json={"date_day": "2026-10-03", "meal_type": "dinner",
              "recipe_id": recipe_id, "weight_g": 150},
        headers=headers,
    )
    log_id = r.json()["id"]

    # 2. приготовили кастрюлю 600 г
    r = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        json={"total_cooked_weight": 600,
              "ingredients": [{"variant_id": 1, "weight_g": 120}]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    pot_id = r.json()["id"]
    assert float(r.json()["current_remaining_weight"]) == 600

    # автоуточнение плана: template_plan → cooked_plan на свежую кастрюлю
    r = await client.get(f"/api/v1/diary/day/2026-10-03", headers=headers)
    plan = next(x for x in r.json() if x["id"] == log_id)
    assert plan["status"] == "cooked_plan"
    assert plan["cooking_log_id"] == pot_id

    # 3. съели порцию 150 г → fact, кастрюля минус 150
    r = await client.post(f"/api/v1/diary/{log_id}/eat", json={"weight_g": 150}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fact"

    r = await client.get("/api/v1/recipes/cooking-logs", headers=headers)
    pot = next(p for p in r.json() if p["id"] == pot_id)
    assert float(pot["current_remaining_weight"]) == 450

    # 4. удалили факт — вес вернулся в кастрюлю
    r = await client.delete(f"/api/v1/diary/{log_id}", headers=headers)
    assert r.status_code == 204, r.text
    r = await client.get("/api/v1/recipes/cooking-logs", headers=headers)
    pot = next(p for p in r.json() if p["id"] == pot_id)
    assert float(pot["current_remaining_weight"]) == 600


async def get_variant_id(client, headers) -> int:
    """ID первой версии продукта текущего пользователя (для кастрюль)."""
    r = await client.get("/api/v1/products/", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()[0]["manufacturers"][0]["variants"][0]["id"]


async def test_pots_isolated_between_users(client):
    vera = await register_and_login(client, "vera2", "vera2@test.com")
    guy = await register_and_login(client, "guy", "guy@test.com")
    _, recipe_id = await build_recipe_stack(client, vera)
    vid = await get_variant_id(client, vera)

    r = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        json={"total_cooked_weight": 500,
              "ingredients": [{"variant_id": vid, "weight_g": 100}]},
        headers=vera,
    )
    assert r.status_code == 201, r.text
    pot_id = r.json()["id"]

    # чужие кастрюли не видны и не редактируются
    r = await client.get("/api/v1/recipes/cooking-logs", headers=guy)
    assert r.json() == []
    r = await client.patch(
        f"/api/v1/recipes/cooking-logs/{pot_id}",
        json={"current_remaining_weight": 1},
        headers=guy,
    )
    assert r.status_code == 404
    r = await client.delete(f"/api/v1/recipes/cooking-logs/{pot_id}", headers=guy)
    assert r.status_code == 404


# --- РЕДАКТИРОВАНИЕ/УДАЛЕНИЕ РЕЦЕПТОВ И СОСТАВА КАСТРЮЛИ ---


async def test_recipe_update_and_delete(client):
    vera = await register_and_login(client, "vera3", "vera3@test.com")
    vid, recipe_id = await build_recipe_stack(client, vera)

    # PATCH: меняем название и состав (добавили второй ингредиент)
    r = await client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={
            "name": "Каша овсяная с мёдом",
            "ingredients": [
                {"variant_id": vid, "weight_g": 60},
                {"variant_id": vid, "weight_g": 10},
            ],
        },
        headers=vera,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Каша овсяная с мёдом"
    assert float(body["total_raw_weight"]) == 70.0
    assert len(body["template_ingredients"]) == 2

    # DELETE чужого рецепта -> 404 (без утечки существования)
    boris = await register_and_login(client, "boris3", "boris3@test.com")
    r = await client.delete(f"/api/v1/recipes/{recipe_id}", headers=boris)
    assert r.status_code == 404

    # DELETE своего -> 204, рецепт исчез
    r = await client.delete(f"/api/v1/recipes/{recipe_id}", headers=vera)
    assert r.status_code == 204, r.text
    r = await client.get(f"/api/v1/recipes/{recipe_id}", headers=vera)
    assert r.status_code == 404


async def test_recipes_isolated_between_users(client):
    """Рецепты — личная библиотека: чужие не видны и недоступны (404 без утечки)."""
    owner = await register_and_login(client, "own1", "own1@test.com")
    thief = await register_and_login(client, "thief1", "thief1@test.com")
    _, recipe_id = await build_recipe_stack(client, owner)

    # список содержит только свои рецепты
    r = await client.get("/api/v1/recipes/", headers=owner)
    assert [x["id"] for x in r.json()] == [recipe_id]
    r = await client.get("/api/v1/recipes/", headers=thief)
    assert r.json() == []

    # чужой рецепт недоступен ни на чтение, ни на изменение/удаление
    assert (await client.get(f"/api/v1/recipes/{recipe_id}", headers=thief)).status_code == 404
    assert (
        await client.patch(f"/api/v1/recipes/{recipe_id}", json={"name": "Взлом"}, headers=thief)
    ).status_code == 404
    assert (await client.delete(f"/api/v1/recipes/{recipe_id}", headers=thief)).status_code == 404

    # дубликат названия внутри своего аккаунта -> 409; у другого пользователя — ок
    rcat = (await client.get("/api/v1/recipes/categories", headers=owner)).json()[0]["id"]
    dup = {
        "name": "Каша овсяная",
        "recipe_category_id": rcat,
        "estimated_cooked_weight": 300,
        "ingredients": [{"variant_id": 1, "weight_g": 60}],
    }
    r = await client.post("/api/v1/recipes/", json=dup, headers=owner)
    assert r.status_code == 409

    # план дневника по чужому рецепту невозможен
    r = await client.post(
        "/api/v1/diary/",
        json={"date_day": "2026-10-03", "meal_type": "lunch",
              "recipe_id": recipe_id, "weight_g": 150},
        headers=thief,
    )
    assert r.status_code == 404


async def test_pot_ingredients_replace(client):
    vera = await register_and_login(client, "vera4", "vera4@test.com")
    guy = await register_and_login(client, "guy4", "guy4@test.com")
    vid, recipe_id = await build_recipe_stack(client, vera)

    r = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        json={"total_cooked_weight": 500,
              "ingredients": [{"variant_id": vid, "weight_g": 100}]},
        headers=vera,
    )
    assert r.status_code == 201, r.text
    pot_id = r.json()["id"]

    # полная замена закладки: было 100 г -> стало два слоя 80+20 = 100 г сырого
    r = await client.put(
        f"/api/v1/recipes/cooking-logs/{pot_id}/ingredients",
        json={"ingredients": [
            {"variant_id": vid, "weight_g": 80},
            {"variant_id": vid, "weight_g": 20},
        ]},
        headers=vera,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["actual_ingredients"]) == 2
    assert float(body["total_raw_weight"]) == 100.0

    # пустой список ингредиентов -> 422 (схема требует min_length=1)
    r = await client.put(
        f"/api/v1/recipes/cooking-logs/{pot_id}/ingredients",
        json={"ingredients": []},
        headers=vera,
    )
    assert r.status_code == 422

    # чужая кастрюля недоступна для замены
    r = await client.put(
        f"/api/v1/recipes/cooking-logs/{pot_id}/ingredients",
        json={"ingredients": [{"variant_id": vid, "weight_g": 1}]},
        headers=guy,
    )
    assert r.status_code == 404


# --- ГОТОВЫЕ ПРОДУКТЫ В ПЛАНЕ (йогурт из магазина и т.п.) ---


async def create_ready_product(client, headers) -> int:
    r = await client.post(
        "/api/v1/products/with-category",
        json={
            "category_name": "Молочные продукты",
            "name": "Йогурт греческий 2%",
            "brand_name": "Теос",
            "base_variant": {
                "manufacturer_name": "Теос",
                "calories": 66,
                "proteins": 8.0,
                "fats": 2.0,
                "carbs": 4.0,
            },
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["manufacturers"][0]["variants"][0]["id"]


async def test_ready_product_plan_eat_and_shopping(client):
    headers = await register_and_login(client, "yana", "yana@test.com")
    oat_variant_id, recipe_id = await build_recipe_stack(client, headers)
    yogurt_id = await create_ready_product(client, headers)

    # План: йогурт 150 г на 2 человек + каша по рецепту
    r = await client.post(
        "/api/v1/diary/",
        json={
            "date_day": "2026-10-10",
            "meal_type": "snack",
            "variant_id": yogurt_id,
            "weight_g": 150,
            "servings_multiplier": 2,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["kind"] == "product"
    assert entry["source_status"] == "product"
    assert "Йогурт" in entry["product_name"]
    assert float(entry["calories"]) == 99.0  # 66 * 1.5
    assert float(entry["proteins"]) == 12.0

    r = await client.post(
        "/api/v1/diary/",
        json={"date_day": "2026-10-11", "meal_type": "breakfast", "recipe_id": recipe_id, "weight_g": 300},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # Список покупок: йогурт «как есть» (150 × 2), овсянка — из рецепта
    r = await client.get(
        "/api/v1/shopping-list",
        params={"start_date": "2026-10-10", "end_date": "2026-10-11"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    items = {i["variant_id"]: i for i in r.json()["items"]}
    assert float(items[yogurt_id]["weight_g"]) == 300.0
    assert items[yogurt_id]["category_name"] == "Молочные продукты"
    assert float(items[oat_variant_id]["weight_g"]) == 60.0

    # Недельный диапазон отдаёт оба типа записей
    r = await client.get(
        "/api/v1/diary/range",
        params={"start_date": "2026-10-10", "end_date": "2026-10-16"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert {e["kind"] for e in r.json()} == {"product", "recipe"}

    # Съели йогурт — факт, в покупки больше не попадает
    r = await client.post(f"/api/v1/diary/{entry['id']}/eat", json={"weight_g": 125}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fact"
    assert float(r.json()["calories"]) == 82.5
    r = await client.get(
        "/api/v1/shopping-list",
        params={"start_date": "2026-10-10", "end_date": "2026-10-10"},
        headers=headers,
    )
    assert r.json()["items"] == []


async def test_diary_entry_requires_exactly_one_source(client):
    headers = await register_and_login(client, "zoe", "zoe@test.com")
    _, recipe_id = await build_recipe_stack(client, headers)
    yogurt_id = await create_ready_product(client, headers)
    base = {"date_day": "2026-10-10", "meal_type": "snack", "weight_g": 100}

    r = await client.post("/api/v1/diary/", json=base, headers=headers)
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/diary/", json={**base, "recipe_id": recipe_id, "variant_id": yogurt_id}, headers=headers
    )
    assert r.status_code == 422
    r = await client.post("/api/v1/diary/", json={**base, "variant_id": 99999}, headers=headers)
    assert r.status_code == 404

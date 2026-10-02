"""Интеграционные API-тесты: весь стек (ASGI + in-memory SQLite).

Проверяют критично важные инварианты:
- аутентификация (регистрация/логин/JWT) и защита эндпоинтов;
- изоляция пользователей в дневнике питания;
- доменная валидация КБЖУ через HTTP.
"""

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


async def test_pots_isolated_between_users(client):
    vera = await register_and_login(client, "vera2", "vera2@test.com")
    guy = await register_and_login(client, "guy", "guy@test.com")
    _, recipe_id = await build_recipe_stack(client, vera)

    r = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        json={"total_cooked_weight": 500,
              "ingredients": [{"variant_id": 1, "weight_g": 100}]},
        headers=vera,
    )
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

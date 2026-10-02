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
        json={"name": "Куриное филе", "category_id": category_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    product_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/products/{product_id}/variants",
        json={"calories": 115, "proteins": 23.0, "fats": 1.9, "carbs": 0.0},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert float(r.json()["calories"]) == 115


async def test_inconsistent_nutrients_rejected(client):
    """КБЖУ не сходится по Атвотеру (4П+9Ж+4У vs ккал) → 422 от доменной валидации."""
    headers = await register_and_login(client, "dave", "dave@test.com")
    r = await client.post("/api/v1/products/categories", json={"name": "Тест"}, headers=headers)
    category_id = r.json()["id"]
    r = await client.post(
        "/api/v1/products/",
        json={"name": "Странный продукт", "category_id": category_id},
        headers=headers,
    )
    product_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/products/{product_id}/variants",
        json={"calories": 100, "proteins": 10, "fats": 5, "carbs": 50},
        headers=headers,
    )
    assert r.status_code in (400, 422), r.text


# --- ДНЕВНИК: ИЗОЛЯЦИЯ ПОЛЬЗОВАТЕЛЕЙ ---


async def test_diary_isolated_between_users(client):
    anna = await register_and_login(client, "anna", "anna@test.com")
    boris = await register_and_login(client, "boris", "boris@test.com")

    r = await client.post(
        "/api/v1/diary/logs",
        json={
            "date": "2026-10-02",
            "meal_type": "lunch",
            "status": "fact",
            "item_name": "Каша",
            "weight_g": 200,
            "calories": 220,
            "proteins": 8,
            "fats": 3,
            "carbs": 40,
        },
        headers=anna,
    )
    assert r.status_code == 201, r.text
    log_id = r.json()["id"]

    # свой лог виден владельцу
    r = await client.get("/api/v1/diary/logs", headers=anna)
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()]
    assert log_id in ids

    # чужой лог недоступен второму пользователю
    r = await client.get("/api/v1/diary/logs", headers=boris)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == []

    r = await client.get(f"/api/v1/diary/logs/{log_id}", headers=boris)
    assert r.status_code in (403, 404)

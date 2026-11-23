"""Общие помощники тестов: пользователь, даты, продукты и рецепты, план, запасы, автоплан.

Тесты импортируют их отсюда (`from tests.helpers import ...`), а не друг из друга."""
from __future__ import annotations


import datetime as dt

from httpx import AsyncClient

from app.core import clock


def day(offset: int = 0) -> str:
    """ISO-дата относительно сегодня: логика холодильника зависит от текущей даты."""
    # то же «сегодня», что у приложения (часовой пояс семьи), — иначе ночью по Москве
    # или на CI в UTC тесты разъезжаются с сервером на сутки
    return (clock.today() + dt.timedelta(days=offset)).isoformat()


TODAY = day()


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


async def get_variant_id(client, headers) -> int:
    """ID первой версии продукта текущего пользователя (для кастрюль)."""
    r = await client.get("/api/v1/products/", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()[0]["manufacturers"][0]["variants"][0]["id"]


async def cook(client, headers, recipe_id, variant_id, cooked_g):
    r = await client.post(
        f"/api/v1/recipes/{recipe_id}/cook",
        json={"total_cooked_weight": cooked_g,
              "ingredients": [{"variant_id": variant_id, "weight_g": 60}]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


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


async def household(client, h) -> dict:
    r = await client.get("/api/v1/household", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def me_id(client, h) -> int:
    return (await household(client, h))["me_member_id"]


async def add_child(client, h, name="Маша", calories=1400) -> int:
    r = await client.post(
        "/api/v1/household/members",
        json={"name": name, "targets": {"calories": calories, "proteins": 50}},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return next(m["id"] for m in r.json()["members"] if m["name"] == name)


async def plan(client, h, *, date_day=TODAY, meal="dinner", recipe_id=None, variant_id=None, portions):
    body = {"date_day": date_day, "meal_type": meal, "portions": portions}
    body["recipe_id" if recipe_id else "variant_id"] = recipe_id or variant_id
    r = await client.post("/api/v1/plan", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def get_item(client, h, item_id, date_day=TODAY) -> dict:
    r = await client.get("/api/v1/plan", params={"start_date": date_day, "end_date": date_day}, headers=h)
    return next(i for i in r.json() if i["id"] == item_id)


async def shopping(client, h, start=TODAY, end=None) -> dict[int, float]:
    r = await client.get("/api/v1/shopping-list", params={"start_date": start, "end_date": end or start}, headers=h)
    assert r.status_code == 200, r.text
    return {i["variant_id"]: float(i["to_buy"]) for i in r.json()["items"]}


async def pot_remaining(client, h, pot_id) -> float:
    pots = (await client.get("/api/v1/recipes/cooking-logs", params={"include_finished": True}, headers=h)).json()
    return float(next(p for p in pots if p["id"] == pot_id)["current_remaining_weight"])


async def add_lot(client, h, product_id, qty, **extra):
    r = await client.post("/api/v1/stock/lots", json={"product_id": product_id, "quantity": qty, **extra}, headers=h)
    assert r.status_code == 201, r.text


async def product_of_variant(client, h, variant_id) -> dict:
    for p in (await client.get("/api/v1/products/", params={"limit": 2000}, headers=h)).json():
        for m in p["manufacturers"]:
            if any(v["id"] == variant_id for v in m["variants"]):
                return p
    raise AssertionError("product not found")


async def set_kcal(client, h, member_id, kcal):
    r = await client.patch(f"/api/v1/household/members/{member_id}", json={"targets": {"calories": kcal}}, headers=h)
    assert r.status_code == 200, r.text


async def product(client, h, name, kcal=40, p=1.0, f=0.5, c=8.0, cat="Овощи") -> tuple[int, int]:
    """(product_id, variant_id)."""
    cats = (await client.get("/api/v1/products/categories", headers=h)).json()
    cat_id = next((x["id"] for x in cats if x["name"] == cat), None)
    if cat_id is None:
        cat_id = (await client.post("/api/v1/products/categories", json={"name": cat}, headers=h)).json()["id"]
    r = await client.post("/api/v1/products/", headers=h, json={
        "name": name, "category_id": cat_id, "brand_name": "Без бренда",
        "base_variant": {"manufacturer_name": "Без бренда", "calories": kcal, "proteins": p, "fats": f, "carbs": c}})
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()["manufacturers"][0]["variants"][0]["id"]


async def recipe(client, h, name, vid, *, cooked=2000, servings=4, **fields) -> int:
    cats = (await client.get("/api/v1/recipes/categories", headers=h)).json()
    cat_id = cats[0]["id"]
    r = await client.post("/api/v1/recipes/", headers=h, json={
        "name": name, "recipe_category_id": cat_id, "estimated_cooked_weight": cooked,
        "default_servings": servings, "ingredients": [{"variant_id": vid, "weight_g": cooked}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    if fields:
        assert (await client.patch(f"/api/v1/recipes/{rid}", json=fields, headers=h)).status_code == 200
    return rid


async def suggest(client, h, start, end, **kw) -> dict:
    r = await client.post("/api/v1/plan/autofill", json={"start": start, "end": end, **kw}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()

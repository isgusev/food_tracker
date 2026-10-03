"""E2E-проверка контрактов API, на которые опирается новый UI (рецепты/холодильник)."""
from __future__ import annotations

import asyncio
import datetime
import os

os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key"

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: E402, F401
from app.db.base import Base  # noqa: E402
from app.db.session import set_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402


async def main() -> None:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=None)
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    set_session_factory(async_sessionmaker(eng, expire_on_commit=False))

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://api"
    ) as ac:
        r = await ac.post("/api/v1/auth/register", json={
            "email": "t@t.ru", "username": "tester", "password": "pass1234"})
        assert r.status_code in (200, 201), r.text
        r = await ac.post("/api/v1/auth/token", data={
            "username": "tester", "password": "pass1234"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await ac.post("/api/v1/recipes/categories",
                          json={"name": "Завтраки"}, headers=h)
        cat_id = r.json()["id"]

        r = await ac.post("/api/v1/products/with-category", headers=h, json={
            "category_name": "Крупы", "name": "Гречка", "brand_name": "Умайн",
            "base_variant": {"calories": 343, "proteins": 13, "fats": 3, "carbs": 62},
        })
        assert r.status_code == 201, r.text
        vid = r.json()["manufacturers"][0]["variants"][0]["id"]

        # создание рецепта — payload нового UI (estimated считается из сырья)
        r = await ac.post("/api/v1/recipes/", headers=h, json={
            "name": "Каша", "recipe_category_id": cat_id,
            "cooking_time_minutes": 20, "instructions": None,
            "default_servings": 2, "estimated_cooked_weight": 425.0,
            "ingredients": [{"variant_id": vid, "weight_g": 500.0}],
        })
        assert r.status_code == 201, r.text
        rec = r.json()
        print("recipe ok, kcal/100g:", rec["calories_per_100g"])

        # готовка — payload нового UI
        r = await ac.post(f"/api/v1/recipes/{rec['id']}/cook", headers=h, json={
            "total_cooked_weight": 425.0,
            "ingredients": [{"variant_id": vid, "weight_g": 500.0}],
        })
        assert r.status_code == 201, r.text
        pot = r.json()
        print("pot ok, remaining:", pot["current_remaining_weight"],
              "actual_ings:", len(pot["actual_ingredients"]))

        # холодильник: список кастрюль
        r = await ac.get("/api/v1/recipes/cooking-logs", headers=h)
        logs = r.json()
        assert len(logs) == 1 and logs[0]["recipe_id"] == rec["id"]

        # «Съел» из холодильника — payload fridge.py
        today = datetime.date.today().isoformat()
        r = await ac.post("/api/v1/diary/", headers=h, json={
            "date_day": today, "meal_type": "lunch",
            "recipe_id": rec["id"], "weight_g": 300.0, "servings_multiplier": 1,
        })
        assert r.status_code == 201, r.text
        log = r.json()
        r = await ac.post(f"/api/v1/diary/{log['id']}/eat",
                          headers=h, json={"weight_g": 300.0})
        assert r.status_code == 200, r.text
        eaten = r.json()
        print("eaten ok, status:", eaten["status"], "kcal:", eaten["calories"])

        r = await ac.get("/api/v1/recipes/cooking-logs", headers=h)
        print("remainder after eat:", r.json()[0]["current_remaining_weight"])

        r = await ac.get(f"/api/v1/diary/day/{today}", headers=h)
        assert len(r.json()) == 1

        # вторая кастрюля по тому же рецепту (несколько блюд)
        r = await ac.post(f"/api/v1/recipes/{rec['id']}/cook", headers=h, json={
            "total_cooked_weight": 800.0,
            "ingredients": [{"variant_id": vid, "weight_g": 941.0}],
        })
        assert r.status_code == 201, r.text
        print("second pot ok:", r.json()["current_remaining_weight"])
        print("ALL E2E OK")


asyncio.run(main())

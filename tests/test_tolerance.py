"""Допуск семьи (Household.portion_tolerance, по умолчанию 15 %): кастрюля вышла
чуть меньше плана — порции уменьшаются пропорционально; в покупках — недобор
до целой упаковки вместо лишней пачки."""
from __future__ import annotations


from decimal import Decimal

import pytest

from app.domain import pick_packages
from tests.test_api import build_recipe_stack, cook, day, register_and_login
from tests.test_plan import add_child, get_item, me_id, plan

pytestmark = pytest.mark.anyio


def test_pick_packages_with_tolerance():
    d = Decimal
    assert pick_packages(d(400), [d(360)], "g") == (d(360), 2)              # строго — две пачки
    assert pick_packages(d(400), [d(360)], "g", d("0.15")) == (d(360), 1)   # −10 % — одна
    assert pick_packages(d(800), [d(360)], "g", d("0.15")) == (d(360), 2)   # 720 из 800
    assert pick_packages(d(500), [d(360)], "g", d("0.15")) == (d(360), 2)   # −28 % — не в допуске
    assert pick_packages(d(300), [d(360)], "g", d("0.15")) == (d(360), 1)   # ноль пачек не бывает
    # ближе к потребности: 400 → 360 (−40) лучше, чем 450 (+50)
    assert pick_packages(d(400), [d(360), d(450)], "g", d("0.15")) == (d(360), 1)


def weights(item) -> dict:
    return {p["member_id"]: float(p["weight_g"]) for p in item["portions"]}


async def two_portions(client, h, recipe_id, a=600, b=390, date_day=None):
    me = await me_id(client, h)
    kid = await add_child(client, h)
    item = await plan(client, h, date_day=date_day or day(1), recipe_id=recipe_id,
                      portions=[{"member_id": me, "weight_g": a}, {"member_id": kid, "weight_g": b}])
    return item, me, kid


async def test_pot_slightly_smaller_shrinks_portions(client):
    h = await register_and_login(client, "tol1", "tol1@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    item, me, kid = await two_portions(client, h, recipe_id)       # 990 г по плану
    await cook(client, h, recipe_id, vid, 960)                     # вышло на 3 % меньше
    got = await get_item(client, h, item["id"], day(1))
    assert got["state"] == "in_fridge" and got["fridge_enough"] is True
    # доли сохранены (600:390), сумма не больше кастрюли
    assert weights(got) == {me: 581.0, kid: 378.0}


async def test_pot_much_smaller_keeps_old_behaviour(client):
    h = await register_and_login(client, "tol2", "tol2@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    item, me, kid = await two_portions(client, h, recipe_id)
    await cook(client, h, recipe_id, vid, 800)                     # −19 % — больше допуска
    got = await get_item(client, h, item["id"], day(1))
    assert got["state"] == "to_cook" and weights(got) == {me: 600.0, kid: 390.0}


async def test_zero_tolerance_is_strict(client):
    h = await register_and_login(client, "tol3", "tol3@test.com")
    r = await client.patch("/api/v1/household", json={"portion_tolerance": 0}, headers=h)
    assert r.status_code == 200 and r.json()["portion_tolerance"] == 0
    assert (await client.patch("/api/v1/household", json={"portion_tolerance": 50}, headers=h)).status_code == 422
    vid, recipe_id = await build_recipe_stack(client, h)
    item, _, _ = await two_portions(client, h, recipe_id)
    await cook(client, h, recipe_id, vid, 980)
    assert (await get_item(client, h, item["id"], day(1)))["state"] == "to_cook"


async def test_ate_more_shrinks_later_portions_within_tolerance(client):
    h = await register_and_login(client, "tol4", "tol4@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    first = await plan(client, h, date_day=day(0), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 300}])
    later = await plan(client, h, date_day=day(1), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 300}])
    await cook(client, h, recipe_id, vid, 600)
    pid = first["portions"][0]["id"]
    r = await client.post(f"/api/v1/plan/portions/{pid}/eat", json={"weight_g": 330}, headers=h)
    assert r.status_code == 200, r.text
    got = await get_item(client, h, later["id"], day(1))
    assert got["state"] == "in_fridge" and weights(got) == {me: 270.0}


async def test_edit_in_plan_keeps_given_weight(client):
    """Правка порции в плане — без допуска: заданный вес не урезаем, блюдо отвязывается."""
    h = await register_and_login(client, "tol5", "tol5@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    await plan(client, h, date_day=day(0), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 300}])
    later = await plan(client, h, date_day=day(1), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 300}])
    await cook(client, h, recipe_id, vid, 600)
    pid = later["portions"][0]["id"]
    r = await client.patch(f"/api/v1/plan/portions/{pid}", json={"weight_g": 320}, headers=h)
    assert r.status_code == 200, r.text
    got = await get_item(client, h, later["id"], day(1))
    assert got["state"] == "to_cook" and weights(got) == {me: 320.0}


async def test_shopping_skips_extra_pack_and_small_shortfall(client):
    h = await register_and_login(client, "tol6", "tol6@test.com")
    r = await client.post("/api/v1/products/with-category", headers=h, json={
        "category_name": "Мясо", "name": "Говядина", "brand_name": "ВкусВилл",
        "package_amount": 360, "package_unit": "g",
        "base_variant": {"calories": 187, "proteins": 18.9, "fats": 12.4, "carbs": 0}})
    assert r.status_code == 201, r.text
    beef = r.json()
    variant_id = beef["manufacturers"][0]["variants"][0]["id"]
    rcat = (await client.post("/api/v1/recipes/categories", json={"name": "Обеды"}, headers=h)).json()["id"]
    r = await client.post("/api/v1/recipes/", headers=h, json={
        "name": "Гуляш", "recipe_category_id": rcat, "estimated_cooked_weight": 990,
        "ingredients": [{"variant_id": variant_id, "weight_g": 400}]})
    assert r.status_code == 201, r.text
    me = await me_id(client, h)
    await plan(client, h, date_day=day(1), recipe_id=r.json()["id"],
               portions=[{"member_id": me, "weight_g": 495}, {"member_id": None, "weight_g": 495}])

    async def beef_line():
        r = await client.get("/api/v1/shopping-list", params={"start_date": day(1), "end_date": day(1)}, headers=h)
        return next((i for i in r.json()["items"] if i["product_id"] == beef["id"]), None)

    line = await beef_line()
    assert float(line["to_buy"]) == 400 and line["package_count"] == 1      # одна пачка 360 г
    await client.post("/api/v1/stock/lots", json={"product_id": beef["id"], "quantity": 360}, headers=h)
    assert await beef_line() is None                                        # 40 г докупать не надо

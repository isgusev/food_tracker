"""Интеграционные тесты финансов (этап 4): цены из партий, стоимость блюд, сводка."""
from __future__ import annotations


import pytest

from tests.test_api import TODAY, build_recipe_stack, cook, create_ready_product, day, register_and_login
from tests.test_plan import me_id, plan
from tests.test_stock import add_lot, product_of_variant

pytestmark = pytest.mark.anyio


async def summary(client, h, start=TODAY, end=None) -> dict:
    r = await client.get("/api/v1/finance/summary", params={"start_date": start, "end_date": end or start}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def test_pot_and_recipe_cost_from_lot_prices(client):
    h = await register_and_login(client, "money", "money@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)          # каша: 60 г овсянки на выход 300 г
    oats = await product_of_variant(client, h, vid)
    await add_lot(client, h, oats["id"], 500, variant_id=vid, price=100)   # 0,20 ₽/г

    r = await client.get("/api/v1/finance/recipe-costs", headers=h)
    rc = next(x for x in r.json() if x["recipe_id"] == recipe_id)
    assert rc["total"] == "12.00" and rc["per_portion"] == "12.00" and rc["priced_share"] == "1.00"

    pot_id = await cook(client, h, recipe_id, vid, 300)
    pc = next(x for x in (await client.get("/api/v1/finance/pot-costs", headers=h)).json() if x["pot_id"] == pot_id)
    assert pc["cost"] == "12.00" and pc["per_100g"] == "4.00" and pc["complete"]

    # готовили, когда овсянки не было в запасах, — стоимость неполная
    await client.post(f"/api/v1/stock/items/{oats['id']}/inventory", json={"quantity": 0}, headers=h)
    pot2 = await cook(client, h, recipe_id, vid, 300)
    pc2 = next(x for x in (await client.get("/api/v1/finance/pot-costs", headers=h)).json() if x["pot_id"] == pot2)
    assert pc2["cost"] is None and not pc2["complete"]


async def test_summary_spent_eaten_wasted_and_budget(client):
    h = await register_and_login(client, "money2", "money2@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    oats = await product_of_variant(client, h, vid)
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)

    # покупки через список: овсянка 500 г за 100 ₽, йогурт 400 г за 80 ₽, ещё одна без цены
    await add_lot(client, h, oats["id"], 500, price=100)          # покупка мимо списка — тоже трата
    me = await me_id(client, h)
    item = await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 200}])
    lst = (await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)).json()
    line = lst["lines"][0]
    await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={"quantity": 400, "price": 80}, headers=h)
    await client.post(f"/api/v1/shopping-lists/{lst['id']}/lines", json={"product_id": oats["id"], "quantity": 100}, headers=h)
    extra = next(x for x in (await client.get("/api/v1/shopping-lists/active", headers=h)).json()["lines"] if x["is_extra"])
    await client.post(f"/api/v1/shopping-lists/lines/{extra['id']}/check", json={}, headers=h)

    s = await summary(client, h)
    assert s["spent"] == "180.00" and s["unpriced_purchases"] == 1
    assert s["by_category"] == [{"name": "Бакалея", "spent": "100.00"}, {"name": "Молочные продукты", "spent": "80.00"}]

    # съели йогурт (200 г × 0,2 ₽) и сварили кашу (60 г овсянки × 0,2 ₽)
    await client.post(f"/api/v1/plan/{item['id']}/eat", headers=h)
    await cook(client, h, recipe_id, vid, 300)
    # испортилось 100 г йогурта
    await client.post(f"/api/v1/stock/items/{yogurt['id']}/write-off", json={"quantity": 100, "note": "скис"}, headers=h)

    s = await summary(client, h)
    assert s["eaten_value"] == "52.00"          # 40 + 12
    assert s["wasted_value"] == "20.00"
    assert s["waste"][0]["name"] == "Йогурт греческий 2%"

    # бюджет
    assert (await client.put("/api/v1/finance/budget", json={"monthly_budget": 15000}, headers=h)).status_code == 204
    assert (await summary(client, h))["monthly_budget"] == "15000.00"


async def test_discarded_pot_counts_as_waste(client):
    h = await register_and_login(client, "money3", "money3@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    oats = await product_of_variant(client, h, vid)
    await add_lot(client, h, oats["id"], 600, price=120)                         # 0,20 ₽/г → кастрюля 12 ₽
    item = await plan(client, h, recipe_id=recipe_id, portions=[{"member_id": await me_id(client, h), "weight_g": 100}])
    pot_id = await cook(client, h, recipe_id, vid, 300)
    await client.post(f"/api/v1/plan/{item['id']}/eat", headers=h)              # съели 100 г из 300
    await client.post(f"/api/v1/recipes/cooking-logs/{pot_id}/discard", headers=h)
    s = await summary(client, h)
    assert s["wasted_value"] == "8.00"           # выброшено 2/3 кастрюли
    assert s["eaten_value"] == "4.00"
    assert s["waste"][0]["reason"] == "выброшен остаток"


async def test_planned_to_buy_estimate_uses_last_price(client):
    h = await register_and_login(client, "money4", "money4@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    await add_lot(client, h, yogurt["id"], 100, price=30)                        # 0,30 ₽/г
    await client.post(f"/api/v1/stock/items/{yogurt['id']}/write-off", json={"quantity": 100}, headers=h)
    await plan(client, h, date_day=day(1), variant_id=yogurt_v, meal="snack", portions=[{"member_id": await me_id(client, h), "weight_g": 250}])
    s = await summary(client, h, TODAY, day(6))
    assert s["planned_to_buy"] == "75.00" and s["planned_unknown"] == 0
    prices = (await client.get("/api/v1/finance/prices", headers=h)).json()
    assert prices[0]["unit_price"].startswith("0.3")

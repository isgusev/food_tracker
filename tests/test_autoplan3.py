"""Автоплан, этап 3 (docs/AUTOPLAN.md, 3.6, 4.1.2, 5): «обычно берём» в покупках, квота снеков,
регулярные готовые продукты в автоплане."""
from __future__ import annotations


import pytest

from tests.test_api import day, register_and_login
from tests.test_autoplan import set_kcal
from tests.test_autoplan2 import product, recipe, suggest
from tests.test_plan import me_id, plan

pytestmark = pytest.mark.anyio


async def bought(client, h, product_id, qty, days_ago, price=None):
    """Покупка в прошлом: срок вышел через 3 дня — в запасах её уже нет, в истории покупок есть."""
    r = await client.post("/api/v1/stock/lots", headers=h, json={
        "product_id": product_id, "quantity": qty, "price": price,
        "purchased_on": day(-days_ago), "expires_on": day(-days_ago + 3)})
    assert r.status_code == 201, r.text


async def regular(client, h, start=None, end=None) -> dict:
    r = await client.get("/api/v1/shopping-list/regular",
                         params={"start_date": start or day(0), "end_date": end or day(6)}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def test_regular_purchases(client):
    h = await register_and_login(client, "rg1", "rg1@test.com")
    milk, _ = await product(client, h, "Молоко 3,2%", cat="Молочное")
    once, _ = await product(client, h, "Ананас", cat="Фрукты")
    for w in (1, 2, 3, 5, 6):                             # 5 из 8 последних недель, по 1–2 литра
        await bought(client, h, milk, 2000 if w == 2 else 1000, 7 * w, price=90)
    await bought(client, h, once, 1000, 14)              # один раз — не «обычно»
    got = (await regular(client, h))["items"]
    assert [(i["name"], float(i["weekly"]), float(i["to_buy"]), i["weeks_bought"]) for i in got] == \
        [("Молоко 3,2%", 1000.0, 1000.0, 5)]
    assert float(got[0]["est_price"]) == 90.0
    # две недели — вдвое больше; дома уже есть 400 мл — меньше
    await client.post("/api/v1/stock/lots", headers=h, json={"product_id": milk, "quantity": 400})
    got = (await regular(client, h, day(0), day(13)))["items"]
    assert float(got[0]["to_buy"]) == 1600.0
    # уже в списке — не предлагаем то, что добавили
    lst = (await client.post("/api/v1/shopping-lists", json={"start_date": day(0), "end_date": day(6)}, headers=h)).json()
    r = await client.post(f"/api/v1/shopping-lists/{lst['id']}/lines", json={"product_id": milk, "quantity": 600}, headers=h)
    assert r.status_code == 201, r.text
    assert (await regular(client, h))["items"] == []
    # «никогда» и «всегда» со своим количеством
    await client.patch(f"/api/v1/stock/items/{milk}", json={"regular": "never"}, headers=h)
    r = await client.patch(f"/api/v1/stock/items/{once}", json={"regular": "always", "regular_qty": 500}, headers=h)
    assert r.status_code == 200, r.text
    got = (await regular(client, h))["items"]
    assert [(i["name"], i["always"], float(i["to_buy"])) for i in got] == [("Ананас", True, 500.0)]
    assert (await client.patch(f"/api/v1/stock/items/{once}", json={"regular": "often"}, headers=h)).status_code == 422


async def test_snack_quota(client):
    h = await register_and_login(client, "rg2", "rg2@test.com")
    choc, _ = await product(client, h, "Шоколад", kcal=540, cat="Сладкое")
    chips, _ = await product(client, h, "Чипсы", kcal=520, cat="Снеки")
    for w in range(1, 6):
        await bought(client, h, choc, 100, 7 * w, price=150)
        await bought(client, h, chips, 150, 7 * w, price=120)
    cats = {c["name"]: c["id"] for c in (await client.get("/api/v1/products/categories", headers=h)).json()}
    r = await client.patch("/api/v1/household/planner", headers=h,
                           json={"snack_categories": [cats["Сладкое"]], "snack_quota": 200})
    assert r.status_code == 200 and r.json()["snack_categories"] == [cats["Сладкое"]]
    got = await regular(client, h)
    assert {i["name"]: i["is_snack"] for i in got["items"]} == {"Шоколад": True, "Чипсы": False}
    # на этой неделе уже купили сладкого (конфеты) на 100 ₽: шоколад за 150 не влезает в 200
    candy, _ = await product(client, h, "Конфеты", kcal=450, cat="Сладкое")
    await client.post("/api/v1/stock/lots", headers=h, json={"product_id": candy, "quantity": 200, "price": 100})
    got = await regular(client, h)
    assert [i["name"] for i in got["items"]] == ["Чипсы"]
    assert got["snacks"] == {"spent": "100.00", "quota": "200.00", "hidden": 1}
    # чипсы — «снек» вручную: тоже в квоту
    await client.patch(f"/api/v1/stock/items/{chips}", json={"is_snack": True}, headers=h)
    assert (await regular(client, h))["items"] == []
    money = (await client.get("/api/v1/finance/summary", params={"start_date": day(-6), "end_date": day(0)}, headers=h)).json()
    assert float(money["snack_spent"]) == 100.0 and float(money["snack_quota"]) == 200.0


async def test_regular_products_in_autoplan(client):
    h = await register_and_login(client, "rg3", "rg3@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, yogurt = await product(client, h, "Йогурт", kcal=70, p=5, cat="Молочное")
    _, bread = await product(client, h, "Хлеб", kcal=250, p=8, cat="Хлеб")
    _, buck = await product(client, h, "Гречка", kcal=110, p=4)
    _, juice = await product(client, h, "Сок", kcal=45, p=0.5, cat="Напитки")
    r = await client.post("/api/v1/recipes/categories", json={"name": "Обеды"}, headers=h)
    assert r.status_code in (200, 201), r.text
    soup = await recipe(client, h, "Гречневый суп", buck, meal_types=["lunch"], keeps_days=1)
    for w in range(1, 6):                                       # 5 недель подряд в этот же день недели
        await plan(client, h, date_day=day(-7 * w), meal="snack", variant_id=yogurt,
                   portions=[{"member_id": me, "weight_g": 150 if w != 3 else 125}])
        await plan(client, h, date_day=day(-7 * w), meal="lunch", recipe_id=soup, portions=[{"member_id": me, "weight_g": 300}])
        await plan(client, h, date_day=day(-7 * w), meal="lunch", variant_id=bread, portions=[{"member_id": me, "weight_g": 50}])
    for w in (1, 2):                                            # 2 раза — не регулярно
        await plan(client, h, date_day=day(-7 * w), meal="breakfast", variant_id=juice,
                   portions=[{"member_id": me, "weight_g": 200}])
    await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": ["lunch", "snack"]})

    got = (await suggest(client, h, day(0), day(6)))["items"]
    today = [(i["meal_type"], i["name"], i["source"]) for i in got if i["date_day"] == day(0)]
    assert ("snack", "Йогурт", "regular") in today and ("lunch", "Хлеб", "side") in today
    assert ("lunch", "Гречневый суп", "cook") in today
    yog = next(i for i in got if i["name"] == "Йогурт")
    assert yog["auto_reason"].startswith("обычно на перекус по ") and float(yog["portions"][0]["weight_g"]) == 150
    assert next(i for i in got if i["name"] == "Хлеб")["auto_reason"].startswith("обычно к обеду по ")
    # йогурт и хлеб — только в свой день недели; сок — нет
    assert {i["date_day"] for i in got if i["variant_id"]} == {day(0)}
    assert not any(i["name"] == "Сок" for i in got)
    # перегенерация заменяет их как обычные предложения; «никогда» — не ставим
    again = await suggest(client, h, day(0), day(6))
    assert again["replaced"] == len(got)
    products = (await client.get("/api/v1/products/", headers=h)).json()
    yog_pid = next(p["id"] for p in products if p["name"] == "Йогурт")
    await client.patch(f"/api/v1/stock/items/{yog_pid}", json={"regular": "never"}, headers=h)
    got = (await suggest(client, h, day(0), day(6)))["items"]
    assert not any(i["name"] == "Йогурт" for i in got)

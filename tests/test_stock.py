"""Интеграционные тесты этапа 3: единицы и упаковки, запасы, общий список покупок."""
from __future__ import annotations


import pytest

from tests.test_api import TODAY, build_recipe_stack, cook, create_ready_product, day, register_and_login
from tests.test_plan import me_id, plan

pytestmark = pytest.mark.anyio


async def product_of_variant(client, h, variant_id) -> dict:
    for p in (await client.get("/api/v1/products/", params={"limit": 2000}, headers=h)).json():
        for m in p["manufacturers"]:
            if any(v["id"] == variant_id for v in m["variants"]):
                return p
    raise AssertionError("product not found")


async def stock(client, h) -> dict[str, dict]:
    r = await client.get("/api/v1/stock", headers=h)
    assert r.status_code == 200, r.text
    return {i["name"]: i for i in r.json()}


async def add_lot(client, h, product_id, qty, **extra):
    r = await client.post("/api/v1/stock/lots", json={"product_id": product_id, "quantity": qty, **extra}, headers=h)
    assert r.status_code == 201, r.text


async def preview(client, h, start=TODAY, end=None) -> dict[str, dict]:
    r = await client.get("/api/v1/shopping-list", params={"start_date": start, "end_date": end or start}, headers=h)
    assert r.status_code == 200, r.text
    return {i["product_name"]: i for i in r.json()["items"]}


YOGURT = "Йогурт греческий 2%"
OATS = "Овсянка"


# --- ЕДИНИЦЫ И УПАКОВКИ ---


async def test_units_and_packages_round_shopping(client):
    h = await register_and_login(client, "unit", "unit@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    me = await me_id(client, h)

    # штучное без веса штуки — нельзя
    r = await client.put(f"/api/v1/products/{yogurt['id']}/unit", json={"base_unit": "pcs"}, headers=h)
    assert r.status_code == 400
    r = await client.put(f"/api/v1/products/{yogurt['id']}/unit", json={"base_unit": "pcs", "piece_weight_g": 125}, headers=h)
    assert r.status_code == 200 and r.json()["base_unit"] == "pcs"
    r = await client.post(f"/api/v1/products/{yogurt['id']}/packages", json={"amount": 4, "name": "упаковка"}, headers=h)
    assert r.status_code == 201 and r.json()["packages"][0]["amount"] == "4.0"
    assert (await client.post(f"/api/v1/products/{yogurt['id']}/packages", json={"amount": 4}, headers=h)).status_code == 409

    # 5 стаканчиков по 125 г на неделю → 2 упаковки по 4 шт
    await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 625}])
    item = (await preview(client, h))[YOGURT]
    assert item["unit"] == "pcs"
    assert float(item["to_buy"]) == 5 and item["package_amount"] == "4.0" and item["package_count"] == 2


async def test_unit_is_shared_by_all_brands_of_item(client):
    h = await register_and_login(client, "brands", "brands@test.com")
    await create_ready_product(client, h)
    r = await client.post("/api/v1/products/with-category", json={
        "category_name": "Молочные продукты", "name": YOGURT, "brand_name": "Другой бренд",
        "base_variant": {"manufacturer_name": "Другой", "calories": 70, "proteins": 8, "fats": 2.5, "carbs": 4}}, headers=h)
    assert r.status_code == 201, r.text
    other = r.json()
    await client.put(f"/api/v1/products/{other['id']}/unit", json={"base_unit": "pcs", "piece_weight_g": 120}, headers=h)
    units = {p["brand"]["name"]: p["base_unit"] for p in (await client.get("/api/v1/products/", params={"q": "йогурт"}, headers=h)).json()}
    assert units == {"Теос": "pcs", "Другой бренд": "pcs"}


# --- ПОКУПКИ = ПОТРЕБНОСТЬ − ЗАПАСЫ ---


async def test_stock_of_any_brand_covers_need(client):
    h = await register_and_login(client, "cover", "cover@test.com")
    yogurt_v = await create_ready_product(client, h)
    r = await client.post("/api/v1/products/with-category", json={
        "category_name": "Молочные продукты", "name": YOGURT, "brand_name": "Другой бренд",
        "base_variant": {"manufacturer_name": "Другой", "calories": 70, "proteins": 8, "fats": 2.5, "carbs": 4}}, headers=h)
    other_brand = r.json()["id"]
    me = await me_id(client, h)
    await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 300}])

    await add_lot(client, h, other_brand, 100)      # дома 100 г йогурта другого бренда
    assert float((await preview(client, h))[YOGURT]["to_buy"]) == 200
    await add_lot(client, h, other_brand, 250)
    assert YOGURT not in await preview(client, h)    # хватает — покупать нечего


async def test_needs_before_period_are_served_first(client):
    h = await register_and_login(client, "before", "before@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    me = await me_id(client, h)
    await plan(client, h, date_day=day(1), variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 100}])
    await plan(client, h, date_day=day(3), variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 100}])
    await add_lot(client, h, yogurt["id"], 150)
    # список на день 3: из 150 г завтра съедим 100 → свободно 50 → купить 50
    item = (await preview(client, h, day(3)))[YOGURT]
    assert float(item["in_stock"]) == 50 and float(item["to_buy"]) == 50


async def test_staples_only_when_marked_low(client):
    h = await register_and_login(client, "salt", "salt@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    oats = await product_of_variant(client, h, vid)
    await plan(client, h, recipe_id=recipe_id, portions=[{"member_id": await me_id(client, h), "weight_g": 300}])
    assert OATS in await preview(client, h)

    await client.patch(f"/api/v1/stock/items/{oats['id']}", json={"is_staple": True}, headers=h)
    assert OATS not in await preview(client, h)
    await client.post(f"/api/v1/products/{oats['id']}/packages", json={"amount": 800}, headers=h)
    await client.patch(f"/api/v1/stock/items/{oats['id']}", json={"is_low": True}, headers=h)
    item = (await preview(client, h))[OATS]
    assert item["is_staple"] and item["package_count"] == 1 and item["to_buy"] is None

    # купили — «заканчивается» снимается
    r = await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)
    line = next(x for x in r.json()["lines"] if x["product_name"] == OATS)
    await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={}, headers=h)
    s = (await stock(client, h))[OATS]
    assert s["is_staple"] and not s["is_low"]


# --- ОБЩИЙ СПИСОК ПОКУПОК ---


async def test_shared_list_check_creates_lot_and_survives_regeneration(client):
    ivan = await register_and_login(client, "shop_i", "shop_i@test.com")
    yogurt_v = await create_ready_product(client, ivan)
    yogurt = await product_of_variant(client, ivan, yogurt_v)
    await client.post(f"/api/v1/products/{yogurt['id']}/packages", json={"amount": 350}, headers=ivan)
    me = await me_id(client, ivan)
    await plan(client, ivan, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 300}])

    r = await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": day(6)}, headers=ivan)
    assert r.status_code == 200, r.text
    lst = r.json()
    [line] = lst["lines"]
    assert line["package_count"] == 1 and line["package_amount"] == "350.0"

    # жена вступила в семью и видит тот же список
    code = (await client.get("/api/v1/household", headers=ivan)).json()["invite_code"]
    anna = await register_and_login(client, "shop_a", "shop_a@test.com")
    await client.post("/api/v1/household/join", json={"invite_code": code}, headers=anna)
    assert (await client.get("/api/v1/shopping-lists/active", headers=anna)).json()["id"] == lst["id"]

    # она отмечает «куплено» с ценой — йогурт в запасах
    r = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={"price": 129.9}, headers=anna)
    assert r.status_code == 200, r.text
    checked = r.json()["lines"][0]
    assert checked["is_checked"] and float(checked["bought_quantity"]) == 350 and float(checked["price"]) == 129.9
    assert float((await stock(client, ivan))[YOGURT]["remaining"]) == 350

    # пересчёт: отмеченное остаётся, новая потребность покрыта запасом — новых строк нет
    r = await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": day(6)}, headers=ivan)
    assert [x["id"] for x in r.json()["lines"]] == [line["id"]]

    # поправили количество и срок у купленного
    r = await client.patch(f"/api/v1/shopping-lists/lines/{line['id']}", json={"quantity": 400, "expires_on": day(5)}, headers=ivan)
    assert r.status_code == 200 and float(r.json()["lines"][0]["bought_quantity"]) == 400
    s = (await stock(client, ivan))[YOGURT]
    assert float(s["remaining"]) == 400 and s["nearest_expiry"] == day(5)

    # снять отметку — партия уходит из запасов
    r = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/uncheck", headers=ivan)
    assert r.status_code == 200 and not r.json()["lines"][0]["is_checked"]
    assert YOGURT not in await stock(client, ivan)

    # внеплановая покупка, удаление строки, закрытие списка
    r = await client.post(f"/api/v1/shopping-lists/{lst['id']}/lines", json={"product_id": yogurt["id"], "quantity": 700}, headers=ivan)
    extra = next(x for x in r.json()["lines"] if x["is_extra"])
    assert extra["package_count"] == 2
    r = await client.delete(f"/api/v1/shopping-lists/lines/{extra['id']}", headers=ivan)
    assert all(not x["is_extra"] for x in r.json()["lines"])
    assert (await client.post(f"/api/v1/shopping-lists/{lst['id']}/close", headers=ivan)).status_code == 204
    assert (await client.get("/api/v1/shopping-lists/active", headers=ivan)).json() is None

    # чужая семья не видит и не трогает
    other = await register_and_login(client, "shop_o", "shop_o@test.com")
    assert (await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={}, headers=other)).status_code == 404


async def test_uncheck_used_purchase_is_refused(client):
    h = await register_and_login(client, "used", "used@test.com")
    yogurt_v = await create_ready_product(client, h)
    me = await me_id(client, h)
    item = await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 150}])
    r = await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)
    line = r.json()["lines"][0]
    await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={"quantity": 500}, headers=h)
    await client.post(f"/api/v1/plan/{item['id']}/eat", headers=h)                 # съели 150 из партии
    r = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/uncheck", headers=h)
    assert r.status_code == 400


# --- РАСХОД: ГОТОВКА И «СЪЕЛ» ---


async def test_cooking_consumes_stock_fifo_and_flags_shortfall(client):
    h = await register_and_login(client, "fifo", "fifo@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    oats = await product_of_variant(client, h, vid)
    await add_lot(client, h, oats["id"], 100, variant_id=vid)                      # без срока
    await add_lot(client, h, oats["id"], 40, variant_id=vid, expires_on=day(2))    # скоро истекает — тратим первой

    pot_id = await cook(client, h, recipe_id, vid, 300)                             # в кастрюлю ушло 60 г
    s = (await stock(client, h))[OATS]
    assert float(s["remaining"]) == 80
    assert [float(lot["remaining"]) for lot in s["lots"]] == [80.0]                 # истекающая партия израсходована
    assert not s["needs_check"]

    # удалили кастрюлю как ошибочную — овсянка вернулась в те же партии
    assert (await client.delete(f"/api/v1/recipes/cooking-logs/{pot_id}", headers=h)).status_code == 204
    s = (await stock(client, h))[OATS]
    assert float(s["remaining"]) == 140 and len(s["lots"]) == 2

    # готовим, когда в запасах меньше нужного: списали что было, товар помечен
    await client.post(f"/api/v1/stock/items/{oats['id']}/write-off", json={"quantity": 120, "note": "просыпали"}, headers=h)
    pot_id = await cook(client, h, recipe_id, vid, 300)
    s = (await stock(client, h))[OATS]
    assert s["needs_check"] and float(s["remaining"]) == 0

    # инвентаризация: на самом деле 500 г — остаток выставлен, пометка снята
    r = await client.post(f"/api/v1/stock/items/{oats['id']}/inventory", json={"quantity": 500}, headers=h)
    assert r.status_code == 200, r.text
    s = (await stock(client, h))[OATS]
    assert float(s["remaining"]) == 500 and not s["needs_check"]

    # правка состава кастрюли списывает только разницу (было 60 — стало 100: ещё 40)
    r = await client.put(f"/api/v1/recipes/cooking-logs/{pot_id}/ingredients",
                         json={"ingredients": [{"variant_id": vid, "weight_g": 100}]}, headers=h)
    assert r.status_code == 200, r.text
    assert float((await stock(client, h))[OATS]["remaining"]) == 460

    reasons = [m["reason"] for m in (await client.get(f"/api/v1/stock/items/{oats['id']}/history", headers=h)).json()]
    assert {"cook", "write_off", "inventory", "manual"} <= set(reasons)


async def test_eating_ready_product_consumes_and_reverts(client):
    h = await register_and_login(client, "eatp", "eatp@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    await add_lot(client, h, yogurt["id"], 500)
    me = await me_id(client, h)
    item = await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": 150}])
    pid = item["portions"][0]["id"]

    await client.post(f"/api/v1/plan/portions/{pid}/eat", json={}, headers=h)
    assert float((await stock(client, h))[YOGURT]["remaining"]) == 350
    await client.patch(f"/api/v1/plan/portions/{pid}", json={"weight_g": 200}, headers=h)
    assert float((await stock(client, h))[YOGURT]["remaining"]) == 300
    await client.post(f"/api/v1/plan/portions/{pid}/uneat", headers=h)
    assert float((await stock(client, h))[YOGURT]["remaining"]) == 500
    await client.post(f"/api/v1/plan/portions/{pid}/eat", json={}, headers=h)
    assert (await client.delete(f"/api/v1/plan/{item['id']}", headers=h)).status_code == 204
    assert float((await stock(client, h))[YOGURT]["remaining"]) == 500


async def test_write_off_never_goes_below_zero(client):
    h = await register_and_login(client, "wroff", "wroff@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    await add_lot(client, h, yogurt["id"], 100)
    await client.post(f"/api/v1/stock/items/{yogurt['id']}/write-off", json={"quantity": 300}, headers=h)
    s = await stock(client, h)
    assert YOGURT not in s or (float(s[YOGURT]["remaining"]) == 0 and not s[YOGURT]["needs_check"])


# --- РЕГРЕССИИ ИЗ РЕВЬЮ ---


async def test_unit_change_blocked_while_anyone_has_stock_and_inherited_by_new_brand(client):
    a = await register_and_login(client, "rega", "rega@test.com")
    yogurt_v = await create_ready_product(client, a)
    yogurt = await product_of_variant(client, a, yogurt_v)
    await client.post(f"/api/v1/products/{yogurt['id']}/packages", json={"amount": 500}, headers=a)
    await add_lot(client, a, yogurt["id"], 600)
    # другая семья не может перевести товар в штуки, пока у семьи A есть остаток
    b = await register_and_login(client, "regb", "regb@test.com")
    r = await client.put(f"/api/v1/products/{yogurt['id']}/unit", json={"base_unit": "pcs", "piece_weight_g": 125}, headers=b)
    assert r.status_code == 409
    assert (await stock(client, a))[YOGURT]["unit"] == "g"

    # остаток обнулили — можно; упаковка 500 г пересчиталась в 4 шт
    await client.post(f"/api/v1/stock/items/{yogurt['id']}/inventory", json={"quantity": 0}, headers=a)
    r = await client.put(f"/api/v1/products/{yogurt['id']}/unit", json={"base_unit": "pcs", "piece_weight_g": 125}, headers=a)
    assert r.status_code == 200 and r.json()["packages"][0]["amount"] == "4.0"

    # новый бренд того же товара наследует единицу
    r = await client.post("/api/v1/products/with-category", json={
        "category_name": "Молочные продукты", "name": YOGURT, "brand_name": "Новый",
        "base_variant": {"manufacturer_name": "Новый", "calories": 70, "proteins": 8, "fats": 2.5, "carbs": 4}}, headers=a)
    assert r.json()["base_unit"] == "pcs" and r.json()["piece_weight_g"] == "125.0"


async def test_pieces_rounding_makes_no_false_shortfall(client):
    h = await register_and_login(client, "eggs", "eggs@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    await client.put(f"/api/v1/products/{yogurt['id']}/unit", json={"base_unit": "pcs", "piece_weight_g": 60}, headers=h)
    await add_lot(client, h, yogurt["id"], 10)
    me = await me_id(client, h)
    for w in (100, 500):   # 1,67 шт + 8,33 шт = ровно 10 шт
        item = await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": me, "weight_g": w}])
        await client.post(f"/api/v1/plan/{item['id']}/eat", headers=h)
    s = (await stock(client, h)).get(YOGURT)
    assert s is None or not s["needs_check"]


async def test_editing_line_quantity_recomputes_packages(client):
    h = await register_and_login(client, "pkg", "pkg@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    await client.post(f"/api/v1/products/{yogurt['id']}/packages", json={"amount": 400}, headers=h)
    await plan(client, h, variant_id=yogurt_v, meal="snack", portions=[{"member_id": await me_id(client, h), "weight_g": 300}])
    line = (await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)).json()["lines"][0]
    r = await client.patch(f"/api/v1/shopping-lists/lines/{line['id']}", json={"quantity": 1200}, headers=h)
    assert r.json()["lines"][0]["package_count"] == 3
    r = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={}, headers=h)
    assert float(r.json()["lines"][0]["bought_quantity"]) == 1200


async def test_staples_never_get_lots(client):
    h = await register_and_login(client, "staple2", "staple2@test.com")
    vid, _ = await build_recipe_stack(client, h)
    oats = await product_of_variant(client, h, vid)
    await client.patch(f"/api/v1/stock/items/{oats['id']}", json={"is_staple": True, "is_low": True}, headers=h)
    assert (await client.post("/api/v1/stock/lots", json={"product_id": oats["id"], "quantity": 100}, headers=h)).status_code == 400
    line = (await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)).json()["lines"][0]
    r = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={}, headers=h)
    assert r.status_code == 200 and r.json()["lines"][0]["bought_quantity"] is None
    s = (await stock(client, h))[OATS]
    assert s["lots"] == [] and not s["is_low"]


async def test_lots_expiring_before_period_are_not_stock(client):
    h = await register_and_login(client, "expire", "expire@test.com")
    yogurt_v = await create_ready_product(client, h)
    yogurt = await product_of_variant(client, h, yogurt_v)
    await add_lot(client, h, yogurt["id"], 500, expires_on=day(1))
    await plan(client, h, date_day=day(3), variant_id=yogurt_v, meal="snack", portions=[{"member_id": await me_id(client, h), "weight_g": 200}])
    assert float((await preview(client, h, day(3)))[YOGURT]["to_buy"]) == 200

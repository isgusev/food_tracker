"""Товары — базовые наименования: предложения объединить похожие, объединение,
одна строка покупок на товар, «именно этот вариант», выбор бренда при покупке."""
from __future__ import annotations


import pytest

from app.services.items import core_tokens
from tests.test_api import TODAY, register_and_login
from tests.test_plan import me_id, plan

pytestmark = pytest.mark.anyio


async def product(client, h, name, brand, category="Молочные продукты") -> dict:
    r = await client.post("/api/v1/products/with-category", headers=h, json={
        "category_name": category, "name": name, "brand_name": brand,
        "base_variant": {"manufacturer_name": brand, "calories": 53, "proteins": 3, "fats": 3.2, "carbs": 4}})
    assert r.status_code == 201, r.text
    p = r.json()
    p["variant_id"] = p["manufacturers"][0]["variants"][0]["id"]
    return p


async def lines(client, h) -> list[dict]:
    r = await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)
    assert r.status_code == 200, r.text
    return [x for x in r.json()["lines"] if not x["is_checked"]]


def test_core_tokens_ignore_brand_size_and_comma():
    assert core_tokens("Кефир 3,2% Домик в деревне 930мл", {"Домик в деревне"}) == core_tokens("кефир 3.2%", set())
    assert core_tokens("Кефир 2,5%", set()) != core_tokens("Кефир 3,2%", set())
    # знак процента суть не меняет: «Кефир 3,2» и «Кефир 3,2%» — один товар
    assert core_tokens("Кефир 3,2", set()) == core_tokens("Кефир 3,2%", set())


async def test_suggest_and_merge_items_one_shopping_line(client):
    h = await register_and_login(client, "item1", "item1@test.com")
    a = await product(client, h, "Кефир 3,2%", "Простоквашино")
    b = await product(client, h, "Кефир 3.2% Домик в деревне", "Домик в деревне")
    c = await product(client, h, "Кефир 2,5%", "Простоквашино")
    assert a["item"]["name"] == "Кефир 3,2%" and a["item_key"] != b["item_key"]

    groups = (await client.get("/api/v1/items/suggestions", headers=h)).json()
    assert len(groups) == 1 and groups[0]["name"] == "Кефир 3,2%"
    assert {i["key"] for i in groups[0]["items"]} == {a["item_key"], b["item_key"]}   # 2,5% — отдельно

    me = await me_id(client, h)
    await plan(client, h, variant_id=a["variant_id"], meal="snack", portions=[{"member_id": me, "weight_g": 300}])
    await plan(client, h, variant_id=b["variant_id"], meal="dinner", portions=[{"member_id": me, "weight_g": 200}])
    assert len(await lines(client, h)) == 2          # пока разные товары — две строки

    r = await client.post("/api/v1/items/merge", headers=h, json={"keys": [a["item_key"], b["item_key"]], "name": "Кефир 3,2%"})
    assert r.status_code == 200, r.text
    assert {p["id"] for p in r.json()["products"]} == {a["id"], b["id"]}
    ls = await lines(client, h)
    assert len(ls) == 1 and ls[0]["product_name"] == "Кефир 3,2%" and float(ls[0]["needed"]) == 500
    # запас любого бренда товара закрывает потребность
    await client.post("/api/v1/stock/lots", json={"product_id": c["id"], "quantity": 999}, headers=h)   # другой товар — не в счёт
    await client.post("/api/v1/stock/lots", json={"product_id": b["id"], "quantity": 400}, headers=h)
    assert float((await lines(client, h))[0]["needed"]) == 100
    assert (await client.get("/api/v1/items/suggestions", headers=h)).json() == []


async def test_exact_variant_separate_line_and_own_stock(client):
    h = await register_and_login(client, "item2", "item2@test.com")
    a = await product(client, h, "Йогурт греческий", "Теос")
    b = await product(client, h, "Йогурт греческий", "Савушкин")      # то же название → тот же товар
    assert a["item_key"] == b["item_key"]
    me = await me_id(client, h)
    await plan(client, h, variant_id=a["variant_id"], meal="snack", portions=[{"member_id": me, "weight_g": 200}])
    r = await client.post("/api/v1/plan", headers=h, json={
        "date_day": TODAY, "meal_type": "breakfast", "variant_id": b["variant_id"], "exact": True,
        "portions": [{"member_id": me, "weight_g": 150}]})
    assert r.status_code == 201 and r.json()["exact"] is True
    ls = {(x["product_name"], x["is_exact"]): x for x in await lines(client, h)}
    assert set(ls) == {("Йогурт греческий", False), ("Йогурт греческий", True)}
    assert ls[("Йогурт греческий", True)]["brand"] == "Савушкин"
    # запас Теоса закрывает обычную строку, но не «именно Савушкин»
    await client.post("/api/v1/stock/lots", json={"product_id": a["id"], "quantity": 500}, headers=h)
    ls = await lines(client, h)
    assert [(x["is_exact"], float(x["needed"])) for x in ls] == [(True, 150.0)]


async def test_check_with_other_brand_of_same_item_only(client):
    h = await register_and_login(client, "item3", "item3@test.com")
    a = await product(client, h, "Масло сливочное 82,5%", "Брест-Литовск")
    b = await product(client, h, "Масло сливочное 82,5%", "Простоквашино")
    other = await product(client, h, "Сметана 20%", "Простоквашино")
    me = await me_id(client, h)
    await plan(client, h, variant_id=a["variant_id"], meal="snack", portions=[{"member_id": me, "weight_g": 100}])
    line = (await lines(client, h))[0]
    bad = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check", json={"product_id": other["id"]}, headers=h)
    assert bad.status_code == 400 and "другой товар" in bad.json()["detail"]
    ok = await client.post(f"/api/v1/shopping-lists/lines/{line['id']}/check",
                           json={"product_id": b["id"], "quantity": 180, "price": 250}, headers=h)
    assert ok.status_code == 200, ok.text
    bought = next(x for x in ok.json()["lines"] if x["is_checked"])
    assert bought["product_id"] == b["id"] and float(bought["bought_quantity"]) == 180
    # «обычно берёте» — теперь Простоквашино
    await plan(client, h, variant_id=a["variant_id"], meal="dinner", portions=[{"member_id": me, "weight_g": 500}])
    fresh = next(x for x in await lines(client, h) if not x["is_extra"])
    assert fresh["product_id"] == b["id"] and fresh["product_name"] == "Масло сливочное 82,5%"


async def test_move_product_to_new_item_and_rename(client):
    h = await register_and_login(client, "item4", "item4@test.com")
    a = await product(client, h, "Сыр", "Viola")
    b = await product(client, h, "Сыр", "Президент")
    r = await client.put(f"/api/v1/items/products/{b['id']}", json={"new_name": "Сыр плавленый"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Сыр плавленый" and [p["id"] for p in r.json()["products"]] == [b["id"]]
    r = await client.patch(f"/api/v1/items/{a['item_key']}", json={"name": "Сыр твёрдый"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Сыр твёрдый"
    names = {i["name"] for i in (await client.get("/api/v1/items", headers=h)).json()}
    assert {"Сыр твёрдый", "Сыр плавленый"} <= names
    # единственный продукт ушёл из товара — пустой товар удалён
    r = await client.put(f"/api/v1/items/products/{b['id']}", json={"item_key": a["item_key"]}, headers=h)
    assert r.status_code == 200 and len(r.json()["products"]) == 2
    assert "Сыр плавленый" not in {i["name"] for i in (await client.get("/api/v1/items", headers=h)).json()}


async def test_product_without_kbju_then_filled(client):
    """Продукт «на потом» (из чека): без КБЖУ, помечен; первые настоящие цифры снимают пометку,
    и рецепты/планы переходят на новую версию."""
    h = await register_and_login(client, "item5", "item5@test.com")
    r = await client.post("/api/v1/products/with-category", headers=h, json={
        "category_name": "Фрукты", "name": "Апельсины", "reuse_existing": True,
        "package_amount": 1000, "package_unit": "g"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["kbju_missing"] is True and p["brand"]["name"] == "Без бренда"
    placeholder = p["manufacturers"][0]["variants"][0]
    assert float(placeholder["calories"]) == 0 and placeholder["is_active"]
    # повтор — тот же продукт, без дублей
    again = await client.post("/api/v1/products/with-category", headers=h, json={
        "category_name": "Фрукты", "name": "апельсины", "reuse_existing": True})
    assert again.status_code == 201 and again.json()["id"] == p["id"]

    r = await client.post(f"/api/v1/products/{p['id']}/variants", headers=h,
                          json={"calories": 43, "proteins": 0.9, "fats": 0.2, "carbs": 8.1})
    assert r.status_code == 201, r.text
    fresh = next(x for x in (await client.get("/api/v1/products/", params={"q": "апельсин"}, headers=h)).json())
    assert fresh["kbju_missing"] is False
    active = [v for m in fresh["manufacturers"] for v in m["variants"] if v["is_active"]]
    assert len(active) == 1 and float(active[0]["calories"]) == 43

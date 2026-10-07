"""Этап 5: штрихкод (Open Food Facts подменён — тесты без сети) и шаблоны недель."""
from __future__ import annotations


import pytest

from app.services import barcode as off
from tests.test_api import TODAY, build_recipe_stack, create_ready_product, day, register_and_login
from tests.test_plan import add_child, me_id, plan

pytestmark = pytest.mark.anyio

OFF_PRODUCT = {
    "product_name": "Greek yogurt", "product_name_ru": "Йогурт греческий 2%", "brands": "Теос, Danone",
    "quantity": "500 г",
    "nutriments": {"energy-kcal_100g": 66, "proteins_100g": 8, "fat_100g": 2, "carbohydrates_100g": 4},
}


def test_parse_quantity():
    assert off.parse_quantity("930 ml") == ("ml", 930)
    assert off.parse_quantity("1 кг") == ("g", 1000)
    assert off.parse_quantity("10 шт") == ("pcs", 10)
    assert off.parse_quantity("1,5 л") == ("ml", 1500)
    assert off.parse_quantity("big pack") == (None, None)


async def test_barcode_lookup_local_then_openfoodfacts(client, monkeypatch):
    h = await register_and_login(client, "scan", "scan@test.com")
    calls = []

    async def fake_fetch(code):
        calls.append(code)
        return OFF_PRODUCT if code == "4600000000017" else None

    monkeypatch.setattr(off, "fetch_off", fake_fetch)

    r = await client.get("/api/v1/products/barcode/4600000000017", headers=h)
    body = r.json()
    assert body["source"] == "openfoodfacts"
    s = body["suggestion"]
    assert s["name"] == "Йогурт греческий 2%" and s["brand"] == "Теос"
    assert s["calories"] == "66.0" and s["package_unit"] == "g" and s["package_amount"] == "500"

    # сохранили с этим штрихкодом — теперь находится в своём справочнике, без внешнего запроса
    r = await client.post("/api/v1/products/with-category", json={
        "category_name": "Молочные продукты", "name": s["name"], "brand_name": s["brand"], "barcode": "4600000000017",
        "base_variant": {"manufacturer_name": s["brand"], "calories": 66, "proteins": 8, "fats": 2, "carbs": 4}}, headers=h)
    assert r.status_code == 201 and r.json()["barcode"] == "4600000000017"
    calls.clear()
    body = (await client.get("/api/v1/products/barcode/4600000000017", headers=h)).json()
    assert body["source"] == "local" and body["product"]["name"] == "Йогурт греческий 2%" and calls == []

    assert (await client.get("/api/v1/products/barcode/1111111111111", headers=h)).json()["source"] == "none"
    assert (await client.get("/api/v1/products/barcode/abc", headers=h)).status_code == 400

    # привязать код к другому продукту нельзя — он занят
    await build_recipe_stack(client, h)
    oats = (await client.get("/api/v1/products/", params={"q": "овсянка"}, headers=h)).json()[0]
    r = await client.put(f"/api/v1/products/{oats['id']}/barcode", json={"barcode": "4600000000017"}, headers=h)
    assert r.status_code == 409
    r = await client.put(f"/api/v1/products/{oats['id']}/barcode", json={"barcode": "4600000000024"}, headers=h)
    assert r.status_code == 200 and r.json()["barcode"] == "4600000000024"


async def test_week_template_save_and_apply(client):
    h = await register_and_login(client, "tmpl", "tmpl@test.com")
    _, recipe_id = await build_recipe_stack(client, h)
    yogurt_v = await create_ready_product(client, h)
    me, child = await me_id(client, h), await add_child(client, h)
    monday = "2026-11-02"
    await plan(client, h, date_day=monday, recipe_id=recipe_id,
               portions=[{"member_id": me, "weight_g": 300}, {"member_id": child, "weight_g": 150}])
    await plan(client, h, date_day="2026-11-04", meal="snack", variant_id=yogurt_v, portions=[{"member_id": child, "weight_g": 125}])

    r = await client.post("/api/v1/plan/templates", json={"name": "Обычная неделя", "week_start": monday}, headers=h)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["items_count"] == 2 and t["meals_per_day"] == {"0": 1, "2": 1}

    # ребёнка скрыли — его порции при применении пропускаются, йогурт без едоков не создаётся
    await client.patch(f"/api/v1/household/members/{child}", json={"is_active": False}, headers=h)
    r = await client.post(f"/api/v1/plan/templates/{t['id']}/apply", json={"week_start": "2026-11-09"}, headers=h)
    assert r.json() == {"created": 1, "skipped": 1}
    items = (await client.get("/api/v1/plan", params={"start_date": "2026-11-09", "end_date": "2026-11-15"}, headers=h)).json()
    assert len(items) == 1 and items[0]["date_day"] == "2026-11-09"
    assert [p["member_id"] for p in items[0]["portions"]] == [me]

    assert (await client.get("/api/v1/plan/templates", headers=h)).json()[0]["name"] == "Обычная неделя"
    other = await register_and_login(client, "tmpl2", "tmpl2@test.com")
    assert (await client.post(f"/api/v1/plan/templates/{t['id']}/apply", json={"week_start": monday}, headers=other)).status_code == 404
    assert (await client.delete(f"/api/v1/plan/templates/{t['id']}", headers=h)).status_code == 204
    r = await client.post("/api/v1/plan/templates", json={"name": "Пусто", "week_start": "2026-12-07"}, headers=h)
    assert r.status_code == 400

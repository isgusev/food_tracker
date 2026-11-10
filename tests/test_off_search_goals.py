"""Поиск в Open Food Facts по названию (сеть подменена), сохранение продукта
с упаковкой одним запросом и расчёт целей КБЖУ под цель."""
from __future__ import annotations


from decimal import Decimal

import pytest

from app.services import barcode as off
from app.services.nutrition import calc_targets
from tests.test_api import register_and_login

pytestmark = pytest.mark.anyio

RAW = [
    {"code": "4600000000031", "product_name": "Молоко &quot;Домик&quot; 2,5%", "brands": "Домик в деревне",
     "brand_owner": "PepsiCo", "product_quantity": "930", "product_quantity_unit": "ml",
     "nutriments": {"energy-kcal_100g": 53, "proteins_100g": 2.9, "fat_100g": 2.5, "carbohydrates_100g": 4.7}},
    {"code": "4600000000048", "product_name": "Творог 5%", "brands": "Простоквашино, Danone",
     "brand_owner": "Простоквашино", "quantity": "200 гр",
     "nutriments": {"energy-kcal_100g": 121, "proteins_100g": 17, "fat_100g": 5, "carbohydrates_100g": 1.8}},
    {"code": "4600000000048", "product_name": "дубль", "brands": "x"},   # тот же код — пропускаем
    {"code": "", "brands": "без названия"},                               # без названия — пропускаем
]


def test_parse_off_manufacturer_package_entities():
    milk = off.parse_off(RAW[0])
    assert milk["name"] == 'Молоко "Домик" 2,5%'
    assert milk["manufacturer"] == "PepsiCo" and milk["brand"] == "Домик в деревне"
    assert (milk["package_unit"], milk["package_amount"]) == ("ml", Decimal("930.0"))
    curd = off.parse_off(RAW[1])
    assert curd["brand"] == "Простоквашино" and curd["manufacturer"] is None  # совпадает с брендом
    assert (curd["package_unit"], curd["package_amount"]) == ("g", Decimal("200"))


async def test_off_search_and_import_with_package(client, monkeypatch):
    h = await register_and_login(client, "offs", "offs@test.com")

    async def fake_search(q, limit=20):
        return RAW
    monkeypatch.setattr(off, "search_off", fake_search)

    r = await client.get("/api/v1/products/off-search", params={"q": "молоко"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] and [i["barcode"] for i in body["items"]] == ["4600000000031", "4600000000048"]
    s = body["items"][0]

    form = {
        "category_name": "Молочные продукты", "name": s["name"], "brand_name": s["brand"],
        "barcode": s["barcode"], "package_amount": s["package_amount"], "package_unit": s["package_unit"],
        "reuse_existing": True,
        "base_variant": {"manufacturer_name": s["manufacturer"], "calories": s["calories"], "proteins": s["proteins"],
                         "fats": s["fats"], "carbs": s["carbs"]},
    }
    r = await client.post("/api/v1/products/with-category", json=form, headers=h)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["barcode"] == "4600000000031" and p["base_unit"] == "ml"   # бутылка → учёт в мл
    assert [float(x["amount"]) for x in p["packages"]] == [930.0]
    assert p["manufacturers"][0]["name"] == "PepsiCo"

    # повторный выбор того же — тот же продукт, без дублей
    r = await client.post("/api/v1/products/with-category", json=form, headers=h)
    assert r.status_code == 201 and r.json()["id"] == p["id"] and len(r.json()["packages"]) == 1
    # без reuse_existing — как раньше, конфликт
    r = await client.post("/api/v1/products/with-category", json={**form, "reuse_existing": False}, headers=h)
    assert r.status_code == 409

    # теперь в поиске он «свой», а не подсказка
    body = (await client.get("/api/v1/products/off-search", params={"q": "молоко"}, headers=h)).json()
    assert [x["id"] for x in body["local"]] == [p["id"]]
    assert [i["barcode"] for i in body["items"]] == ["4600000000048"]


async def test_off_search_unavailable(client, monkeypatch):
    h = await register_and_login(client, "offd", "offd@test.com")

    async def down(q, limit=20):
        return None
    monkeypatch.setattr(off, "search_off", down)
    r = await client.get("/api/v1/products/off-search", params={"q": "сыр"}, headers=h)
    assert r.status_code == 200 and r.json() == {"available": False, "items": [], "local": []}
    assert (await client.get("/api/v1/products/off-search", params={"q": "с"}, headers=h)).status_code in (400, 422)


async def test_existing_by_name_gets_barcode_and_package(client):
    h = await register_and_login(client, "offn", "offn@test.com")
    base = {"category_name": "Бакалея", "name": "Гречка", "brand_name": "Увелка",
            "base_variant": {"calories": 313, "proteins": 12.6, "fats": 3.3, "carbs": 57.1}}
    p = (await client.post("/api/v1/products/with-category", json=base, headers=h)).json()
    r = await client.post("/api/v1/products/with-category", headers=h, json={
        **base, "name": "гречка", "barcode": "4600000000055", "package_amount": 800, "package_unit": "g",
        "reuse_existing": True})
    assert r.status_code == 201 and r.json()["id"] == p["id"]
    assert r.json()["barcode"] == "4600000000055" and [float(x["amount"]) for x in r.json()["packages"]] == [800.0]


def test_calc_targets_mifflin_and_goals():
    # мужчина 30 лет, 180 см, 80 кг: ВОО = 9,99·80 + 6,25·180 − 4,92·30 + 5 = 1781,6
    m = calc_targets("m", 30, Decimal(180), Decimal(80), Decimal("1.6"), "maintain")
    assert m.bmr == 1782 and m.maintenance == 2851
    assert m.calories == 2850 and m.fats == 95                   # 30 % / 9
    assert m.proteins == 93                                      # 13 % при КФА 1,6
    assert m.carbs == round((2850 - 93 * 4 - 95 * 9) / 4)
    lose = calc_targets("m", 30, Decimal(180), Decimal(80), Decimal("1.6"), "lose")
    gain = calc_targets("m", 30, Decimal(180), Decimal(80), Decimal("1.6"), "gain")
    assert lose.calories == 2420 and gain.calories == 3140       # −15 % / +10 %
    assert lose.proteins == gain.proteins == 128                 # 1,6 г/кг

    # маленькая женщина на снижении — не ниже 1200 ккал
    w = calc_targets("f", 60, Decimal(150), Decimal(45), Decimal("1.4"), "lose")
    assert w.calories == 1200 and any("1200" in n for n in w.notes)

    with pytest.raises(Exception):
        calc_targets("m", 12, Decimal(150), Decimal(40), Decimal("1.6"), "maintain")


async def test_profile_saved_and_calc_endpoint(client):
    h = await register_and_login(client, "goal", "goal@test.com")
    hh = (await client.get("/api/v1/household", headers=h)).json()
    mid = hh["me_member_id"]
    profile = {"sex": "f", "birth_year": 1990, "height_cm": 165, "weight_kg": 60, "activity": 1.6, "goal": "lose"}
    r = await client.post("/api/v1/household/targets/calc", json=profile, headers=h)
    assert r.status_code == 200, r.text
    calc = r.json()
    assert float(calc["targets"]["calories"]) < float(calc["maintenance"]) and calc["age"] > 18
    r = await client.patch(f"/api/v1/household/members/{mid}", headers=h,
                           json={"profile": profile, "targets": calc["targets"]})
    me = next(m for m in r.json()["members"] if m["id"] == mid)
    assert me["profile"]["goal"] == "lose" and float(me["profile"]["weight_kg"]) == 60
    assert float(me["targets"]["calories"]) == float(calc["targets"]["calories"])
    bad = await client.post("/api/v1/household/targets/calc", json={**profile, "birth_year": 2020}, headers=h)
    assert bad.status_code == 400


# --- Поиск по неточному вводу: нормализация, ранжирование, обход ограничений OFF ---
PITA = [
    {"code": "1", "product_name": "Пита", "brands": "Пекарня Марии"},
    {"code": "2", "product_name": "Пита Турецкая", "brands": "Русский хлеб"},
    {"code": "3", "product_name": "Пита &quot;Ливанская&quot;", "brands": "ВкусВилл"},
    {"code": "3", "product_name": "дубль", "brands": "x"},
]


def test_normalize_and_match_score():
    assert off.normalize_query('Пита "Ливанская') == "пита ливанская"
    assert off.normalize_query("Молоко 2,5% «Домик», ёж.") == "молоко 2,5% домик еж"
    full = 'Пита "Ливанская" ВкусВилл'
    assert off.match_score("Пита Ливанская", full) == 1
    assert off.match_score("Пита Лива", full) > off.match_score("Пита Лива", "Пита Турецкая")   # начало слова
    assert off.match_score("Пита Леванская", full) > 0.8                                    # опечатка
    assert off.match_score("Пита Леванская", "Пита Турецкая") == 0.5


@pytest.mark.parametrize("query", ["Пита Ливанская", "Пита Лива", "Пита Леванская", 'пита "ливанская'])
async def test_search_off_ranks_and_broadens(monkeypatch, query):
    off._search_cache.clear()
    calls = []

    async def classic(q, limit):
        calls.append(q)
        # как у OFF: только целые слова — недописанное/с опечаткой не находится
        return [p for p in PITA if all(w in off.normalize_query(p["product_name"]) for w in q.split())]

    async def new(q, limit):
        calls.append("new:" + q)
        return PITA[:2]
    monkeypatch.setattr(off, "_search_classic", classic)
    monkeypatch.setattr(off, "_search_new", new)
    result = await off.search_off(query, 10)
    assert result[0]["code"] == "3"                          # нужная пита первой
    assert [p["code"] for p in result].count("3") == 1       # без дублей


async def test_search_off_unavailable_only_when_all_sources_fail(monkeypatch):
    off._search_cache.clear()

    async def down(q, limit):
        return None
    monkeypatch.setattr(off, "_search_classic", down)
    monkeypatch.setattr(off, "_search_new", down)
    assert await off.search_off("пита ливанская") is None

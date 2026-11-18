"""Автоплан, этап 2 (docs/AUTOPLAN.md, 4.1–4.3): оценка блюд, генерация готовок, «другой вариант»,
принять / закрепить, настройки планировщика."""
from __future__ import annotations


import datetime as dt

import pytest

from app.core import clock
from app.services.autoplan import Scoring, _Board
from tests.test_api import build_recipe_stack, day, register_and_login
from tests.test_autoplan import set_kcal
from tests.test_plan import get_item, me_id, plan

pytestmark = pytest.mark.anyio


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


async def items_in(client, h, start, end) -> list[dict]:
    r = await client.get("/api/v1/plan", params={"start_date": start, "end_date": end}, headers=h)
    return r.json()


def test_scoring_rest_expiry_share_repeat():
    class R:
        def __init__(self, id, name, effort="easy", kcal=100, prot=5):
            self.id, self.name, self.effort = id, name, effort
            self.calories_per_100g, self.proteins_per_100g = kcal, prot
    today = dt.date(2026, 11, 20)
    soup, stew = R(1, "Суп"), R(2, "Рагу")
    sc = Scoring(
        keys={1: {"кабачок": "Кабачок", "морковь": "Морковь"}, 2: {"морковь": "Морковь"}},
        last_cooked={1: today - dt.timedelta(days=3), 2: today - dt.timedelta(days=20)},
        expiring={"кабачок": (today + dt.timedelta(days=1), "Кабачок")},
        protein_target=0.2,
    )
    board = _Board()
    s1, why1 = sc.score(soup, today, board)
    s2, why2 = sc.score(stew, today, board)
    # суп недавно был, но кабачок скоро испортится: 3/14 + 0,8 × ½ + 0,3 × (0,2/0,2) ; рагу — 1 + 0,3
    assert why1 == "кабачок до 21.11" and why2 == "не готовили 20 дн"
    assert round(s1, 3) == round(3 / 14 + 0.4 + 0.3, 3) and round(s2, 3) == 1.3
    # выбрали суп сегодня — у рагу общий товар, суп завтра — штраф за повтор
    board.put(today, "dinner", soup, sc.keys[1])
    s2b, _ = sc.score(stew, today + dt.timedelta(days=1), board)
    assert round(s2b - s2, 3) == 0.4                               # общий товар: 0,4 × 1/1
    s1b, _ = sc.score(soup, today + dt.timedelta(days=1), board)
    assert s1b < 0.5


async def test_planner_settings(client):
    h = await register_and_login(client, "pl1", "pl1@test.com")
    r = await client.get("/api/v1/household/planner", headers=h)
    assert r.json() == {"meal_types": None, "no_cook_days": [], "special_days": [], "max_special_per_week": 1,
                        "snack_categories": [], "snack_quota": None}
    r = await client.patch("/api/v1/household/planner", headers=h, json={
        "meal_types": ["dinner", "lunch"], "no_cook_days": [4, 4], "special_days": [5], "max_special_per_week": 2})
    assert r.status_code == 200, r.text
    assert r.json() == {"meal_types": ["lunch", "dinner"], "no_cook_days": [4], "special_days": [5],
                        "max_special_per_week": 2, "snack_categories": [], "snack_quota": None}
    r = await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": None, "no_cook_days": []})
    assert r.json()["meal_types"] is None and r.json()["no_cook_days"] == [] and r.json()["special_days"] == [5]
    assert (await client.patch("/api/v1/household/planner", headers=h, json={"no_cook_days": [7]})).status_code == 422
    assert (await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": []})).status_code == 422


async def test_generate_week(client):
    h = await register_and_login(client, "pl2", "pl2@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    oats_vid, porridge = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{porridge}", json={"meal_types": ["breakfast"], "keeps_days": 1}, headers=h)
    zucchini, zuc_vid = await product(client, h, "Кабачок")
    _, carrot_vid = await product(client, h, "Морковь")
    soup = await recipe(client, h, "Суп", zuc_vid, meal_types=["lunch", "dinner"])
    stew = await recipe(client, h, "Рагу", carrot_vid, meal_types=["lunch", "dinner"])
    pilaf = await recipe(client, h, "Плов", carrot_vid, meal_types=["dinner"], effort="special")
    await recipe(client, h, "Не в ротации", carrot_vid, in_rotation=False)
    # кабачок портится послезавтра — суп получит причину; пятница-день недели +3 — «без готовки»
    r = await client.post("/api/v1/stock/lots", headers=h,
                          json={"product_id": zucchini, "quantity": 500, "expires_on": day(2)})
    assert r.status_code == 201, r.text
    no_cook = (clock.today() + dt.timedelta(days=3)).weekday()
    await client.patch("/api/v1/household/planner", headers=h,
                       json={"meal_types": ["breakfast", "lunch", "dinner"], "no_cook_days": [no_cook]})
    manual = await plan(client, h, date_day=day(1), meal="lunch", recipe_id=stew, portions=[{"member_id": me, "weight_g": 300}])

    preview = await suggest(client, h, day(0), day(6), dry_run=True)
    out = await suggest(client, h, day(0), day(6))
    got = out["items"]
    assert [(i["date_day"], i["meal_type"], i["recipe_id"]) for i in preview["items"]] == \
        [(i["date_day"], i["meal_type"], i["recipe_id"]) for i in got]
    cells = {(i["date_day"], i["meal_type"]) for i in got}
    assert (day(1), "lunch") not in cells and all(i["meal_type"] != "snack" for i in got)
    names = {(i["date_day"], i["name"]) for i in got}
    assert len(names) == len(got)                                     # одно блюдо — не дважды за день
    assert all(i["date_day"] != day(3) or i["source"] == "continue" for i in got)   # без готовки
    weeks = [dt.date.fromisoformat(i["date_day"]).isocalendar()[1] for i in got
             if i["recipe_id"] == pilaf and i["source"] == "cook"]
    assert len(weeks) == len(set(weeks))                              # «эдакое» — не больше 1 в неделю
    assert all(i["recipe_id"] == porridge for i in got if i["meal_type"] == "breakfast")
    first_soup = next(i for i in got if i["recipe_id"] == soup)
    assert "кабачок до" in first_soup["auto_reason"] and first_soup["source"] == "cook"
    # закладка супа (2000 г, порция 500) — тот же приём следующего дня
    cont = [i for i in got if i["source"] == "continue"]
    assert cont and all(i["auto_reason"].startswith("та же закладка") for i in cont)
    assert all(float(i["portions"][0]["weight_g"]) == 500 for i in got if i["recipe_id"] == soup)

    # перегенерация: прежние предложения заменяются тем же (детерминированно), ручное не трогается
    again = await suggest(client, h, day(0), day(6))
    assert again["replaced"] == len(got)
    assert [(i["date_day"], i["meal_type"], i["recipe_id"]) for i in again["items"]] == \
        [(i["date_day"], i["meal_type"], i["recipe_id"]) for i in got]
    assert (await get_item(client, h, manual["id"], day(1)))["origin"] == "manual"


async def test_pin_accept_alternative(client):
    h = await register_and_login(client, "pl3", "pl3@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, a_vid = await product(client, h, "Гречка", kcal=110, p=4)
    _, b_vid = await product(client, h, "Рис", kcal=120, p=3)
    _, c_vid = await product(client, h, "Курица", kcal=160, p=20, cat="Мясо")
    _, porridge = await build_recipe_stack(client, h)   # категория рецептов; кашу из ротации убираем
    await client.patch(f"/api/v1/recipes/{porridge}", json={"in_rotation": False}, headers=h)
    ids = [await recipe(client, h, n, v, meal_types=["dinner"], keeps_days=1)
           for n, v in (("Гречка с грибами", a_vid), ("Рис с овощами", b_vid), ("Курица запечённая", c_vid))]
    await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": ["dinner"]})
    got = (await suggest(client, h, day(0), day(1)))["items"]
    assert len(got) == 2 and got[0]["recipe_id"] == ids[2]           # больше белка — выше оценка
    first, second = got[0]["item_id"], got[1]["item_id"]

    # 📌 закрепить — перегенерация не трогает, блюдо остаётся предложением
    r = await client.patch(f"/api/v1/plan/{first}", json={"pinned": True}, headers=h)
    assert r.status_code == 200 and r.json()["pinned"] and r.json()["origin"] == "auto"
    again = await suggest(client, h, day(0), day(1))
    assert again["replaced"] == 1 and [i["date_day"] for i in again["items"]] == [day(1)]
    second = again["items"][0]["item_id"]

    # 🔄 другой вариант: следующий по оценке, по кругу (гречка → рис → курица → гречка)
    assert (await get_item(client, h, second, day(1)))["recipe_id"] == ids[0]
    cur, seq = second, []
    for _ in range(3):
        r = await client.post(f"/api/v1/plan/{cur}/alternative", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["origin"] == "auto" and r.json()["date_day"] == day(1) and r.json()["auto_reason"]
        seq.append(r.json()["recipe_id"])
        cur = r.json()["id"]
    assert seq == [ids[1], ids[2], ids[0]]

    # ✓ принять одно и «Принять всё»
    r = await client.post(f"/api/v1/plan/{cur}/accept", headers=h)
    assert r.json()["origin"] == "manual" and r.json()["auto_reason"] is None
    r = await client.post("/api/v1/plan/accept", json={"start": day(0), "end": day(1)}, headers=h)
    assert r.json() == {"accepted": 1}
    assert all(i["origin"] == "manual" for i in await items_in(client, h, day(0), day(1)))
    # принятое — обычный план: новая генерация его не заменяет
    assert (await suggest(client, h, day(0), day(1)))["replaced"] == 0
    r = await client.post(f"/api/v1/plan/{cur}/alternative", headers=h)
    assert r.status_code == 200   # для ручного блюда «другой вариант» тоже работает


async def test_special_days_and_week_limit(client):
    h = await register_and_login(client, "pl4", "pl4@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, v = await product(client, h, "Баранина", kcal=200, p=25, cat="Мясо")
    _, w = await product(client, h, "Капуста", kcal=30, p=1)
    _, porridge = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{porridge}", json={"in_rotation": False}, headers=h)
    special = await recipe(client, h, "Плов", v, meal_types=["dinner"], effort="special", keeps_days=1)
    await recipe(client, h, "Щи", w, meal_types=["dinner"], keeps_days=1)
    await recipe(client, h, "Тушёная капуста", w, meal_types=["dinner"], keeps_days=1)
    sat = (clock.today() + dt.timedelta(days=2)).weekday()
    await client.patch("/api/v1/household/planner", headers=h,
                       json={"meal_types": ["dinner"], "special_days": [sat], "max_special_per_week": 1})
    got = (await suggest(client, h, day(0), day(6)))["items"]
    specials = [i["date_day"] for i in got if i["recipe_id"] == special]
    assert specials == [day(2)]
    assert next(i for i in got if i["recipe_id"] == special)["auto_reason"]


async def test_freezer_goes_to_no_cook_day(client):
    from tests.test_api import cook
    h = await register_and_login(client, "pl5", "pl5@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    vid, rid = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{rid}", json={"in_rotation": False, "meal_types": ["dinner"]}, headers=h)
    pot = await cook(client, h, rid, vid, 3000)
    await client.post(f"/api/v1/recipes/cooking-logs/{pot}/freeze", json={}, headers=h)   # годна 60 дней
    free_day = (clock.today() + dt.timedelta(days=2)).weekday()
    await client.patch("/api/v1/household/planner", headers=h,
                       json={"meal_types": ["dinner"], "no_cook_days": [free_day]})
    got = (await suggest(client, h, day(0), day(4)))["items"]
    assert [(i["date_day"], i["source"]) for i in got] == [(day(2), "freezer")]
    assert got[0]["cooking_log_id"] == pot and "заготовка" in got[0]["auto_reason"]

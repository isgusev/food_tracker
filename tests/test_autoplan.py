"""Автоплан, этап 1 (docs/AUTOPLAN.md): поля рецепта, происхождение блюд плана, типичные порции,
заготовки в морозилке и заполнение пустых ячеек из холодильника и морозилки."""
from __future__ import annotations


from decimal import Decimal

import pytest

from app.services.autoplan import typical_from
from tests.test_api import build_recipe_stack, cook, day, register_and_login
from tests.test_plan import add_child, get_item, me_id, plan

pytestmark = pytest.mark.anyio


async def set_kcal(client, h, member_id, kcal):
    r = await client.patch(f"/api/v1/household/members/{member_id}", json={"targets": {"calories": kcal}}, headers=h)
    assert r.status_code == 200, r.text


async def autofill(client, h, start, end, **kw):
    r = await client.post("/api/v1/plan/autofill", json={"start": start, "end": end, **kw}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_recipe_planning_fields(client):
    h = await register_and_login(client, "ap1", "ap1@test.com")
    _, rid = await build_recipe_stack(client, h)
    r = (await client.get(f"/api/v1/recipes/{rid}", headers=h)).json()
    assert (r["in_rotation"], r["effort"], r["meal_types"], r["keeps_days"], r["is_freezable"]) == (True, "easy", None, 2, False)
    r = await client.patch(f"/api/v1/recipes/{rid}", headers=h, json={
        "effort": "special", "meal_types": ["dinner", "breakfast", "dinner"], "keeps_days": 3,
        "is_freezable": True, "in_rotation": False})
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["meal_types"] == ["breakfast", "dinner"] and r["effort"] == "special" and r["keeps_days"] == 3
    assert r["is_freezable"] and not r["in_rotation"]
    r = await client.patch(f"/api/v1/recipes/{rid}", headers=h, json={"meal_types": None})
    assert r.json()["meal_types"] is None                                  # снова «любые»
    assert (await client.patch(f"/api/v1/recipes/{rid}", headers=h, json={"meal_types": ["brunch"]})).status_code == 422
    assert (await client.patch(f"/api/v1/recipes/{rid}", headers=h, json={"effort": "hard"})).status_code == 422


def test_typical_portion_rules():
    class M:
        def __init__(self, id, kcal):
            self.id, self.target_calories = id, kcal
    me, wife, kid = M(1, 2400), M(2, 1800), M(3, None)
    d = Decimal
    # история есть у меня — у остальных пропорционально цели ккал (ребёнок без цели — 2000)
    t = typical_from([me, wife, kid], {1: [d(400), d(500), d(450)]}, "lunch", d(100))
    assert t[1] == (d(450), "history") and t[2] == (d(340), "family") and t[3] == (d(375), "family")
    # истории нет — доля цели на приём пищи: 1800 × 25 % / 150 ккал на 100 г = 300 г
    assert typical_from([wife], {}, "breakfast", d(150))[2] == (d(300), "target")
    # у рецепта есть стандартная порция (выход / порций) — она, с поправкой на цель: грибы 61 ккал не дадут кило
    assert typical_from([wife, kid], {}, "lunch", d(61), standard=d(140)) == {2: (d(125), "recipe"), 3: (d(140), "recipe")}


async def test_typical_portions_endpoint(client):
    h = await register_and_login(client, "ap2", "ap2@test.com")
    vid, rid = await build_recipe_stack(client, h)          # шаблон: 76 ккал / 100 г
    me = await me_id(client, h)
    await set_kcal(client, h, me, 1520)
    r = await client.get("/api/v1/plan/typical-portions", params={"meal_type": "breakfast", "recipe_id": rid}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == [{"member_id": me, "weight_g": "500", "source": "target"}]   # 1520 × 0,25 / 76 × 100
    item = await plan(client, h, recipe_id=rid, portions=[{"member_id": me, "weight_g": 280}])
    await client.post(f"/api/v1/plan/{item['id']}/eat", headers=h)
    r = await client.get("/api/v1/plan/typical-portions", params={"meal_type": "lunch", "recipe_id": rid}, headers=h)
    assert r.json()[0]["weight_g"] == "280" and r.json()[0]["source"] == "history"
    bad = await client.get("/api/v1/plan/typical-portions", params={"meal_type": "lunch"}, headers=h)
    assert bad.status_code == 400


async def test_autofill_from_fridge_only_empty_cells(client):
    h = await register_and_login(client, "ap3", "ap3@test.com")
    vid, rid = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    # вчерашняя история: ем 300 г этого блюда
    past = await plan(client, h, date_day=day(-1), recipe_id=rid, portions=[{"member_id": me, "weight_g": 300}])
    await client.post(f"/api/v1/plan/{past['id']}/eat", headers=h)
    manual = await plan(client, h, date_day=day(0), meal="lunch", recipe_id=rid, portions=[{"member_id": me, "weight_g": 200}])
    pot_id = await cook(client, h, rid, vid, 900)            # обед сегодня привязался: свободно 700
    await client.patch(f"/api/v1/recipes/{rid}", headers=h, json={"keeps_days": 3})

    preview = await autofill(client, h, day(0), day(5), dry_run=True)
    assert all(i["item_id"] is None for i in preview)
    items = await autofill(client, h, day(0), day(5))
    # сегодня рецепт уже в плане (обед) — второй раз за день не ставим; дальше по одному в день, пока свежо;
    # приёмы пищи у рецепта не отмечены — любой, первый пустой (завтрак)
    assert [(i["date_day"], i["meal_type"]) for i in items] == [(day(1), "breakfast"), (day(2), "breakfast")]
    assert [i["date_day"] for i in items] == [i["date_day"] for i in preview]
    assert all(i["cooking_log_id"] == pot_id and "остаток в холодильнике" in i["auto_reason"] for i in items)
    assert [float(i["portions"][0]["weight_g"]) for i in items] == [300.0, 300.0]

    got = await get_item(client, h, items[0]["item_id"], day(1))
    assert got["origin"] == "auto" and got["state"] == "in_fridge" and got["auto_reason"]
    assert (await get_item(client, h, manual["id"]))["origin"] == "manual"
    # повторно — ячейки заняты, ничего нового; ручная правка делает блюдо обычным
    assert await autofill(client, h, day(0), day(5)) == []
    pid = got["portions"][0]["id"]
    await client.patch(f"/api/v1/plan/portions/{pid}", json={"weight_g": 250}, headers=h)
    got = await get_item(client, h, items[0]["item_id"], day(1))
    assert got["origin"] == "manual" and got["auto_reason"] is None


async def test_autofill_shrinks_last_portion_within_tolerance_and_respects_meal_types(client):
    h = await register_and_login(client, "ap4", "ap4@test.com")
    vid, rid = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    past = await plan(client, h, date_day=day(-1), recipe_id=rid, portions=[{"member_id": me, "weight_g": 300}])
    await client.post(f"/api/v1/plan/{past['id']}/eat", headers=h)
    await client.patch(f"/api/v1/recipes/{rid}", headers=h, json={"keeps_days": 5, "meal_types": ["breakfast"]})
    await cook(client, h, rid, vid, 570)                     # 300 + 270: второй — в пределах допуска
    items = await autofill(client, h, day(0), day(4))
    assert [(i["date_day"], i["meal_type"]) for i in items] == [(day(0), "breakfast"), (day(1), "breakfast")]
    assert [float(i["portions"][0]["weight_g"]) for i in items] == [300.0, 270.0]
    assert await autofill(client, h, day(0), day(4), meal_types=["lunch"]) == []


async def test_freeze_and_autofill_from_freezer(client):
    h = await register_and_login(client, "ap5", "ap5@test.com")
    vid, rid = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    await set_kcal(client, h, me, 500)                       # обед ≈ 460 г при 38 ккал / 100 г
    pot_id = await cook(client, h, rid, vid, 600)
    r = await client.post(f"/api/v1/recipes/cooking-logs/{pot_id}/freeze", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["is_frozen"] and r.json()["keeps_until"] == day(60) and r.json()["good_until"] == day(60)
    # срок далеко — автоплан заготовку не трогает
    assert await autofill(client, h, day(0), day(6)) == []
    r = await client.post(f"/api/v1/recipes/cooking-logs/{pot_id}/freeze", json={"keeps_until": day(3)}, headers=h)
    assert r.json()["keeps_until"] == day(3)
    items = await autofill(client, h, day(0), day(6))
    assert items and all("заготовка в морозилке" in i["auto_reason"] for i in items)
    assert max(i["date_day"] for i in items) <= day(3)
    assert (await client.post(f"/api/v1/recipes/cooking-logs/{pot_id}/freeze", json={"keeps_until": day(-1)},
                              headers=h)).status_code == 400
    r = await client.post(f"/api/v1/recipes/cooking-logs/{pot_id}/unfreeze", headers=h)
    assert r.status_code == 200 and not r.json()["is_frozen"] and r.json()["good_until"] == day(1)
    pots = (await client.get("/api/v1/recipes/cooking-logs", headers=h)).json()
    assert pots[0]["good_until"] == day(1)


async def test_autofill_period_validation_and_family_portions(client):
    h = await register_and_login(client, "ap6", "ap6@test.com")
    vid, rid = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    kid = await add_child(client, h, calories=1000)
    await set_kcal(client, h, me, 2000)
    past = await plan(client, h, date_day=day(-1), recipe_id=rid, portions=[{"member_id": me, "weight_g": 400}])
    await client.post(f"/api/v1/plan/{past['id']}/eat", headers=h)
    await cook(client, h, rid, vid, 600)
    items = await autofill(client, h, day(0), day(0))
    assert len(items) == 1
    w = {p["member_id"]: float(p["weight_g"]) for p in items[0]["portions"]}
    assert w == {me: 400.0, kid: 200.0}                          # ребёнку — по цели ккал от моей истории
    r = await client.post("/api/v1/plan/autofill", json={"start": day(3), "end": day(0)}, headers=h)
    assert r.status_code == 422

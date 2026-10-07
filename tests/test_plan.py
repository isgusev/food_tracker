"""Интеграционные тесты семьи и плана питания: порции по людям, холодильник, покупки."""
from __future__ import annotations


import pytest

from tests.test_api import (
    TODAY,
    build_recipe_stack,
    cook,
    create_ready_product,
    day,
    register_and_login,
)

pytestmark = pytest.mark.anyio

# Каша: 60 г овсянки (380 ккал/100 г = 228 ккал) на выход 300 г → 76 ккал/100 г


async def household(client, h) -> dict:
    r = await client.get("/api/v1/household", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def me_id(client, h) -> int:
    return (await household(client, h))["me_member_id"]


async def add_child(client, h, name="Маша", calories=1400) -> int:
    r = await client.post(
        "/api/v1/household/members",
        json={"name": name, "targets": {"calories": calories, "proteins": 50}},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return next(m["id"] for m in r.json()["members"] if m["name"] == name)


async def plan(client, h, *, date_day=TODAY, meal="dinner", recipe_id=None, variant_id=None, portions):
    body = {"date_day": date_day, "meal_type": meal, "portions": portions}
    body["recipe_id" if recipe_id else "variant_id"] = recipe_id or variant_id
    r = await client.post("/api/v1/plan", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def get_item(client, h, item_id, date_day=TODAY) -> dict:
    r = await client.get("/api/v1/plan", params={"start_date": date_day, "end_date": date_day}, headers=h)
    return next(i for i in r.json() if i["id"] == item_id)


async def shopping(client, h, start=TODAY, end=None) -> dict[int, float]:
    r = await client.get("/api/v1/shopping-list", params={"start_date": start, "end_date": end or start}, headers=h)
    assert r.status_code == 200, r.text
    return {i["variant_id"]: float(i["to_buy"]) for i in r.json()["items"]}


async def pot_remaining(client, h, pot_id) -> float:
    pots = (await client.get("/api/v1/recipes/cooking-logs", params={"include_finished": True}, headers=h)).json()
    return float(next(p for p in pots if p["id"] == pot_id)["current_remaining_weight"])


def portion_of(item, member_id):
    return next(p for p in item["portions"] if p["member_id"] == member_id)


# --- СЕМЬЯ ---


async def test_household_created_on_first_use_with_members_and_targets(client):
    h = await register_and_login(client, "ivan", "ivan@test.com")
    hh = await household(client, h)
    assert hh["name"] == "Семья ivan"
    assert len(hh["invite_code"]) == 8
    [me] = hh["members"]
    assert me["is_me"] and me["username"] == "ivan"

    child = await add_child(client, h)
    r = await client.patch(
        f"/api/v1/household/members/{child}",
        json={"targets": {"calories": 1500, "proteins": 55, "fats": 50, "carbs": 190}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    m = next(x for x in r.json()["members"] if x["id"] == child)
    assert float(m["targets"]["calories"]) == 1500 and m["user_id"] is None

    # себя (участника с аккаунтом) скрыть нельзя, ребёнка — можно
    r = await client.patch(f"/api/v1/household/members/{me['id']}", json={"is_active": False}, headers=h)
    assert r.status_code == 400
    r = await client.patch(f"/api/v1/household/members/{child}", json={"is_active": False}, headers=h)
    assert r.status_code == 200


async def test_join_by_code_moves_data_into_family(client):
    ivan = await register_and_login(client, "ivan2", "ivan2@test.com")
    _, ivan_recipe = await build_recipe_stack(client, ivan)
    code = (await household(client, ivan))["invite_code"]

    anna = await register_and_login(client, "anna2", "anna2@test.com")
    r = await client.post("/api/v1/recipes/categories", json={"name": "Супы"}, headers=anna)
    rcat = r.json()["id"]
    vid = (await client.get("/api/v1/products/", headers=anna)).json()[0]["manufacturers"][0]["variants"][0]["id"]
    r = await client.post(
        "/api/v1/recipes/",
        json={"name": "Суп Анны", "recipe_category_id": rcat, "estimated_cooked_weight": 1000,
              "ingredients": [{"variant_id": vid, "weight_g": 100}]},
        headers=anna,
    )
    assert r.status_code == 201, r.text

    # чужой рецепт до вступления не виден
    assert (await client.get(f"/api/v1/recipes/{ivan_recipe}", headers=anna)).status_code == 404

    assert (await client.post("/api/v1/household/join", json={"invite_code": "WRONG123"}, headers=anna)).status_code == 404
    r = await client.post("/api/v1/household/join", json={"invite_code": code.lower()}, headers=anna)
    assert r.status_code == 200, r.text
    assert {m["username"] for m in r.json()["members"]} == {"ivan2", "anna2"}

    # теперь у обоих общая библиотека: рецепт Ивана + переехавший рецепт Анны
    names_anna = {x["name"] for x in (await client.get("/api/v1/recipes/", headers=anna)).json()}
    names_ivan = {x["name"] for x in (await client.get("/api/v1/recipes/", headers=ivan)).json()}
    assert names_anna == names_ivan == {"Каша овсяная", "Суп Анны"}

    # из семьи, где есть другие взрослые, уйти по коду нельзя
    other = await register_and_login(client, "oleg2", "oleg2@test.com")
    other_code = (await household(client, other))["invite_code"]
    r = await client.post("/api/v1/household/join", json={"invite_code": other_code}, headers=ivan)
    assert r.status_code == 409


async def test_plan_isolated_between_families(client):
    a = await register_and_login(client, "fam_a", "fam_a@test.com")
    b = await register_and_login(client, "fam_b", "fam_b@test.com")
    _, recipe_id = await build_recipe_stack(client, a)
    item = await plan(client, a, recipe_id=recipe_id, portions=[{"member_id": await me_id(client, a), "weight_g": 200}])

    r = await client.get("/api/v1/plan", params={"start_date": TODAY, "end_date": TODAY}, headers=b)
    assert r.json() == []
    assert (await client.delete(f"/api/v1/plan/{item['id']}", headers=b)).status_code == 404
    pid = item["portions"][0]["id"]
    assert (await client.post(f"/api/v1/plan/portions/{pid}/eat", json={}, headers=b)).status_code == 404
    # порцию на чужого члена семьи не добавить
    r = await client.post(
        "/api/v1/plan",
        json={"date_day": TODAY, "meal_type": "lunch", "recipe_id": recipe_id,
              "portions": [{"member_id": await me_id(client, b), "weight_g": 100}]},
        headers=a,
    )
    assert r.status_code == 404


# --- ПОРЦИИ, КБЖУ, ПОКУПКИ ---


async def test_portions_per_person_kbju_and_shopping(client):
    h = await register_and_login(client, "petr", "petr@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me, child = await me_id(client, h), await add_child(client, h)

    item = await plan(client, h, recipe_id=recipe_id, portions=[
        {"member_id": me, "weight_g": 300},
        {"member_id": child, "weight_g": 150},
        {"member_id": None, "weight_g": 150},   # гость
    ])
    assert item["state"] == "to_cook" and item["kind"] == "recipe"
    assert float(portion_of(item, me)["calories"]) == 228.0      # 300 г × 76 ккал/100 г
    assert float(portion_of(item, child)["calories"]) == 114.0
    guest = portion_of(item, None)
    assert guest["member_name"] is None
    assert float(item["remaining_weight_g"]) == 600

    # покупки: 600 г готового из выхода 300 г → две закладки = 120 г овсянки
    assert (await shopping(client, h))[vid] == 120.0

    # дубликат порции одного человека в блюде — 422; ровно один источник — 422
    r = await client.post("/api/v1/plan", json={"date_day": TODAY, "meal_type": "lunch", "recipe_id": recipe_id,
                                                  "portions": [{"member_id": me, "weight_g": 1}, {"member_id": me, "weight_g": 2}]},
                          headers=h)
    assert r.status_code == 422
    r = await client.post("/api/v1/plan", json={"date_day": TODAY, "meal_type": "lunch", "portions": [{"weight_g": 1}]}, headers=h)
    assert r.status_code == 422


async def test_ready_product_for_family(client):
    h = await register_and_login(client, "yana", "yana@test.com")
    yogurt = await create_ready_product(client, h)
    me, child = await me_id(client, h), await add_child(client, h)
    item = await plan(client, h, variant_id=yogurt, meal="snack",
                      portions=[{"member_id": me, "weight_g": 150}, {"member_id": child, "weight_g": 125}])
    assert item["kind"] == "product" and item["state"] == "product"
    assert "Йогурт" in item["name"]
    assert float(portion_of(item, me)["calories"]) == 99.0       # 66 × 1.5
    assert (await shopping(client, h))[yogurt] == 275.0

    # ребёнок съел — в покупках остаётся только моя порция
    r = await client.post(f"/api/v1/plan/portions/{portion_of(item, child)['id']}/eat", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert (await shopping(client, h))[yogurt] == 150.0


# --- ХОЛОДИЛЬНИК ---


async def test_cooking_reserves_only_items_that_fit_from_today(client):
    """Регрессия: готовка не должна «съедать» прошлые и не влезающие будущие блюда."""
    h = await register_and_login(client, "kira", "kira@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me, child = await me_id(client, h), await add_child(client, h)

    stale = await plan(client, h, date_day=day(-2), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 300}])
    today_item = await plan(client, h, recipe_id=recipe_id, portions=[
        {"member_id": me, "weight_g": 300}, {"member_id": child, "weight_g": 200}])
    later = await plan(client, h, date_day=day(6), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 300}])

    pot_id = await cook(client, h, recipe_id, vid, 600)

    assert (await get_item(client, h, stale["id"], day(-2)))["state"] == "to_cook"
    t = await get_item(client, h, today_item["id"])
    assert t["state"] == "in_fridge" and t["cooking_log_id"] == pot_id
    assert float(t["fridge_reserved_g"]) == 500
    assert (await get_item(client, h, later["id"], day(6)))["state"] == "to_cook"
    # через неделю каша снова в покупках: 300 г из выхода 300 г → 60 г овсянки
    assert (await shopping(client, h, TODAY, day(6)))[vid] == 60.0


async def test_eating_portions_from_pot(client):
    h = await register_and_login(client, "lev", "lev@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me, child = await me_id(client, h), await add_child(client, h)
    dinner = await plan(client, h, recipe_id=recipe_id, portions=[
        {"member_id": me, "weight_g": 200}, {"member_id": child, "weight_g": 100}])
    tomorrow = await plan(client, h, date_day=day(1), meal="lunch", recipe_id=recipe_id,
                          portions=[{"member_id": me, "weight_g": 150}])
    pot_id = await cook(client, h, recipe_id, vid, 500)
    assert (await get_item(client, h, tomorrow["id"], day(1)))["state"] == "in_fridge"

    # я съел больше плана (300 вместо 200): КБЖУ — по кастрюле (228 ккал на 500 г)
    r = await client.post(f"/api/v1/plan/portions/{portion_of(dinner, me)['id']}/eat",
                          json={"weight_g": 300}, headers=h)
    assert r.status_code == 200, r.text
    mine = portion_of(r.json(), me)
    assert mine["is_eaten"] and mine["eaten_from_pot_id"] == pot_id
    assert float(mine["calories"]) == 136.8
    assert await pot_remaining(client, h, pot_id) == 200

    # остаток 200: резерв = ребёнок 100 + завтра 150 = 250 → завтрашний обед отвязан
    t = await get_item(client, h, tomorrow["id"], day(1))
    assert t["state"] == "to_cook"

    # «все поели» — доедает ребёнок
    r = await client.post(f"/api/v1/plan/{dinner['id']}/eat", headers=h)
    assert r.status_code == 200, r.text
    assert all(p["is_eaten"] for p in r.json()["portions"])
    assert await pot_remaining(client, h, pot_id) == 100

    # правка съеденного сверх остатка — ошибка, а не молчаливое обнуление
    r = await client.patch(f"/api/v1/plan/portions/{portion_of(dinner, me)['id']}",
                           json={"weight_g": 500}, headers=h)
    assert r.status_code == 400

    # отмена «съедено» и удаление блюда возвращают вес в кастрюлю
    r = await client.post(f"/api/v1/plan/portions/{portion_of(dinner, child)['id']}/uneat", headers=h)
    assert r.status_code == 200, r.text
    assert await pot_remaining(client, h, pot_id) == 200
    assert (await client.delete(f"/api/v1/plan/{dinner['id']}", headers=h)).status_code == 204
    assert await pot_remaining(client, h, pot_id) == 500


async def test_eat_more_than_pot_has_fails(client):
    h = await register_and_login(client, "gleb", "gleb@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    item = await plan(client, h, recipe_id=recipe_id, portions=[{"member_id": await me_id(client, h), "weight_g": 200}])
    pot_id = await cook(client, h, recipe_id, vid, 250)
    r = await client.post(f"/api/v1/plan/portions/{item['portions'][0]['id']}/eat", json={"weight_g": 300}, headers=h)
    assert r.status_code == 400
    assert await pot_remaining(client, h, pot_id) == 250


async def test_new_item_reserves_existing_pot_only_when_it_fits(client):
    h = await register_and_login(client, "sasha", "sasha@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me, child = await me_id(client, h), await add_child(client, h)
    pot_id = await cook(client, h, recipe_id, vid, 300)

    fits = await plan(client, h, date_day=day(1), recipe_id=recipe_id,
                      portions=[{"member_id": me, "weight_g": 100}, {"member_id": child, "weight_g": 100}])
    too_much = await plan(client, h, date_day=day(2), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 150}])
    assert fits["state"] == "in_fridge" and fits["cooking_log_id"] == pot_id
    assert too_much["state"] == "to_cook" and too_much["fridge_enough"] is False
    # в покупки — только то, что не помещается: 150 из 300 → 30 г овсянки
    assert (await shopping(client, h, day(1), day(2)))[vid] == 30.0


async def test_manual_remainder_releases_items(client):
    h = await register_and_login(client, "mila", "mila@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    item = await plan(client, h, date_day=day(1), recipe_id=recipe_id,
                      portions=[{"member_id": await me_id(client, h), "weight_g": 300}])
    pot_id = await cook(client, h, recipe_id, vid, 400)
    assert (await get_item(client, h, item["id"], day(1)))["state"] == "in_fridge"
    r = await client.patch(f"/api/v1/recipes/cooking-logs/{pot_id}", json={"current_remaining_weight": 100}, headers=h)
    assert r.status_code == 200, r.text
    assert (await get_item(client, h, item["id"], day(1)))["state"] == "to_cook"


async def test_delete_pot_keeps_eaten_without_fridge(client):
    h = await register_and_login(client, "vera", "vera@test.com")
    vid, recipe_id = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    eaten = await plan(client, h, recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 100}])
    later = await plan(client, h, date_day=day(1), recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 100}])
    pot_id = await cook(client, h, recipe_id, vid, 300)
    await client.post(f"/api/v1/plan/{eaten['id']}/eat", headers=h)

    r = await client.get(f"/api/v1/recipes/cooking-logs/{pot_id}/usage", headers=h)
    assert r.json() == {"past_dates": [], "current_future_dates": [TODAY, day(1)]}
    r = await client.delete(f"/api/v1/recipes/cooking-logs/{pot_id}", headers=h)
    assert r.status_code == 204, r.text

    e = await get_item(client, h, eaten["id"])
    assert e["portions"][0]["is_eaten"] and e["portions"][0]["eaten_from_pot_id"] is None
    assert float(e["portions"][0]["calories"]) == 76.0   # КБЖУ — по шаблону рецепта
    assert (await get_item(client, h, later["id"], day(1)))["state"] == "to_cook"


# --- ПРОЧЕЕ ---


async def test_day_sorted_by_meal_order_and_move(client):
    h = await register_and_login(client, "nina", "nina@test.com")
    _, recipe_id = await build_recipe_stack(client, h)
    me = await me_id(client, h)
    ids = {}
    for meal in ("snack", "dinner", "lunch", "breakfast"):
        ids[meal] = (await plan(client, h, date_day=day(3), meal=meal, recipe_id=recipe_id,
                                portions=[{"member_id": me, "weight_g": 100}]))["id"]
    r = await client.get("/api/v1/plan", params={"start_date": day(3), "end_date": day(3)}, headers=h)
    assert [i["meal_type"] for i in r.json()] == ["breakfast", "lunch", "dinner", "snack"]

    r = await client.patch(f"/api/v1/plan/{ids['snack']}", json={"date_day": day(4), "meal_type": "lunch"}, headers=h)
    assert r.status_code == 200 and r.json()["date_day"] == day(4) and r.json()["meal_type"] == "lunch"


async def test_portion_add_and_last_portion_delete_removes_item(client):
    h = await register_and_login(client, "rita", "rita@test.com")
    _, recipe_id = await build_recipe_stack(client, h)
    me, child = await me_id(client, h), await add_child(client, h)
    item = await plan(client, h, recipe_id=recipe_id, portions=[{"member_id": me, "weight_g": 200}])

    r = await client.post(f"/api/v1/plan/{item['id']}/portions", json={"member_id": child, "weight_g": 120}, headers=h)
    assert r.status_code == 201 and len(r.json()["portions"]) == 2
    r = await client.post(f"/api/v1/plan/{item['id']}/portions", json={"member_id": child, "weight_g": 1}, headers=h)
    assert r.status_code == 400

    item = r_item = (await get_item(client, h, item["id"]))
    r = await client.delete(f"/api/v1/plan/portions/{portion_of(item, child)['id']}", headers=h)
    assert r.status_code == 200 and len(r.json()["portions"]) == 1
    r = await client.delete(f"/api/v1/plan/portions/{portion_of(r_item, me)['id']}", headers=h)
    assert r.status_code == 204
    r = await client.get("/api/v1/plan", params={"start_date": TODAY, "end_date": TODAY}, headers=h)
    assert r.json() == []

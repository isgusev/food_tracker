"""Автоплан, этап 4 (docs/AUTOPLAN.md, 3.4, 4.2): отзывы о предложениях и их учёт в оценке."""
from __future__ import annotations


import datetime as dt
from types import SimpleNamespace

import pytest

from app.core import clock
from app.services.autoplan import feedback_scores
from tests.helpers import build_recipe_stack, day, me_id, plan, product, recipe, register_and_login, set_kcal, suggest

pytestmark = pytest.mark.anyio


def fb(action, days_ago=0, recipe_id=1, item_key=None):
    when = dt.datetime.combine(clock.today() - dt.timedelta(days=days_ago), dt.time(12))
    return SimpleNamespace(action=action, recipe_id=recipe_id, item_key=item_key, created_at=when)


def test_feedback_scores_decay_dedupe_cap():
    today = clock.today()
    rec, items = feedback_scores([fb("pinned"), fb("removed", 30, recipe_id=2)], today)
    assert rec[1] == 1.0 and round(rec[2], 3) == -0.5            # месяц — вдвое слабее
    # три дня одной закладки убрали в один день — один минус; другой день — ещё один
    rec, _ = feedback_scores([fb("removed"), fb("removed"), fb("removed"), fb("removed", 1)], today)
    assert round(rec[1], 3) == round(-1 - 0.5 ** (1 / 30), 3)
    rec, _ = feedback_scores([fb("pinned", d) for d in range(5)], today)
    assert rec[1] == 2.0                                          # не больше потолка
    _, items = feedback_scores([fb("removed", recipe_id=None, item_key="йогурт")], today)
    assert items == {"йогурт": -1.0}


async def two_dinners(client, h):
    """Два ужина в ротации: «Курица» (больше белка — выше оценка) и «Гречка»; каша убрана из ротации."""
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, porridge = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{porridge}", json={"in_rotation": False}, headers=h)
    _, chicken_v = await product(client, h, "Курица", kcal=160, p=20, cat="Мясо")
    _, buck_v = await product(client, h, "Гречка", kcal=110, p=4)
    chicken = await recipe(client, h, "Курица запечённая", chicken_v, meal_types=["dinner"], keeps_days=1)
    buck = await recipe(client, h, "Гречка с грибами", buck_v, meal_types=["dinner"], keeps_days=1)
    await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": ["dinner"]})
    return me, chicken, buck


async def test_removed_suggestion_loses_to_other(client):
    h = await register_and_login(client, "fb1", "fb1@test.com")
    _, chicken, buck = await two_dinners(client, h)
    got = (await suggest(client, h, day(0), day(0)))["items"]
    assert [i["recipe_id"] for i in got] == [chicken]
    # ✕ — убрали предложение: в следующий раз на эту ячейку — гречка
    assert (await client.delete(f"/api/v1/plan/{got[0]['item_id']}", headers=h)).status_code == 204
    got = (await suggest(client, h, day(0), day(0)))["items"]
    assert [i["recipe_id"] for i in got] == [buck]
    # 📌 закрепили гречку — дальше она в плюсе и с причиной
    await client.patch(f"/api/v1/plan/{got[0]['item_id']}", json={"pinned": False}, headers=h)
    r = await client.patch(f"/api/v1/plan/{got[0]['item_id']}", json={"pinned": True}, headers=h)
    assert r.status_code == 200
    # через 5 дней (без штрафа за повтор): курица в минусе за ✕, гречка в плюсе за 📌
    nxt = (await suggest(client, h, day(5), day(5)))["items"]
    assert [i["recipe_id"] for i in nxt] == [buck] and nxt[0]["auto_reason"] == "семья часто выбирает"


async def test_replaced_suggestion_loses_its_cell(client):
    h = await register_and_login(client, "fb2", "fb2@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, porridge = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{porridge}", json={"in_rotation": False}, headers=h)
    _, v1 = await product(client, h, "Кабачок", kcal=40, p=1)
    _, v2 = await product(client, h, "Тыква", kcal=40, p=1)
    first = await recipe(client, h, "Рагу из кабачков", v1, meal_types=["dinner"], keeps_days=1)
    second = await recipe(client, h, "Рагу из тыквы", v2, meal_types=["dinner"], keeps_days=1)
    await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": ["dinner"]})
    got = (await suggest(client, h, day(0), day(0)))["items"]
    assert [i["recipe_id"] for i in got] == [first]                 # равные оценки — первый по номеру
    r = await client.post(f"/api/v1/plan/{got[0]['item_id']}/alternative", headers=h)
    assert r.json()["recipe_id"] == second
    # новый подбор той же ячейки: заменённый 🔄 в минусе — остаётся второй
    again = (await suggest(client, h, day(0), day(0)))["items"]
    assert again and [i["recipe_id"] for i in again] == [second]


async def test_deleting_manual_dish_is_not_feedback(client):
    """Ручное блюдо удалили — это не отзыв: курица так и идёт первой."""
    h2 = await register_and_login(client, "fb3", "fb3@test.com")
    me2, chicken2, _ = await two_dinners(client, h2)
    manual = await plan(client, h2, date_day=day(5), recipe_id=chicken2, portions=[{"member_id": me2, "weight_g": 300}])
    assert (await client.delete(f"/api/v1/plan/{manual['id']}", headers=h2)).status_code == 204
    got = (await suggest(client, h2, day(0), day(0)))["items"]
    assert [i["recipe_id"] for i in got] == [chicken2]


async def test_favorite_recipe_comes_back_sooner(client):
    """Любимое: блюдо, которое семья часто ставит сама, обгоняет новое, как только прошло несколько дней."""
    h = await register_and_login(client, "fav1", "fav1@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, porridge = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{porridge}", json={"in_rotation": False}, headers=h)
    _, v1 = await product(client, h, "Кабачок", kcal=40, p=1)
    _, v2 = await product(client, h, "Тыква", kcal=40, p=1)
    new = await recipe(client, h, "Рагу из кабачков", v1, meal_types=["dinner"], keeps_days=1)
    fav = await recipe(client, h, "Рагу из тыквы", v2, meal_types=["dinner"], keeps_days=1)
    await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": ["dinner"]})
    for w in range(1, 7):                                  # 6 недель из 8 — сами ставили на ужин
        await plan(client, h, date_day=day(-7 * w), recipe_id=fav, portions=[{"member_id": me, "weight_g": 300}])
    # неделю назад было — ещё рано (новое блюдо впереди); через 3 дня — любимое обгоняет
    assert [i["recipe_id"] for i in (await suggest(client, h, day(0), day(0), dry_run=True))["items"]] == [new]
    assert [i["recipe_id"] for i in (await suggest(client, h, day(3), day(3), dry_run=True))["items"]] == [fav]


async def test_daily_habit_and_two_steps_of_dislike(client, session_factory):
    """Йогурт на перекус почти каждый день — предлагается каждый день; два «убрать» в разные дни —
    через день; ещё два — не предлагается."""
    from app.models.plan import PlanFeedback

    h = await register_and_login(client, "fav2", "fav2@test.com")
    me = await me_id(client, h)
    await set_kcal(client, h, me, 2000)
    _, porridge = await build_recipe_stack(client, h)
    await client.patch(f"/api/v1/recipes/{porridge}", json={"in_rotation": False}, headers=h)
    yog_pid, yogurt = await product(client, h, "Йогурт", kcal=70, p=5, cat="Молочное")
    for d in range(1, 15):                                 # две недели — каждый день
        await plan(client, h, date_day=day(-d), meal="snack", variant_id=yogurt, portions=[{"member_id": me, "weight_g": 150}])
    await client.patch("/api/v1/household/planner", headers=h, json={"meal_types": ["snack"]})
    got = (await suggest(client, h, day(0), day(5), dry_run=True))["items"]
    assert [i["date_day"] for i in got] == [day(k) for k in range(6)]
    assert got[0]["auto_reason"] == "обычно на перекус"

    from app.models.product import Product
    async with session_factory() as s:
        item_key = (await s.get(Product, yog_pid)).item_key
    hid = (await client.get("/api/v1/household", headers=h)).json()["id"]

    async def removed(*days_ago):
        async with session_factory() as s:
            for d in days_ago:
                s.add(PlanFeedback(household_id=hid, item_key=item_key, meal_type="snack", action="removed",
                                   created_at=dt.datetime.combine(clock.today() - dt.timedelta(days=d), dt.time(9))))
            await s.commit()

    await removed(2, 1)                                    # два «убрать» в разные дни — реже, через день
    got = (await suggest(client, h, day(0), day(5), dry_run=True))["items"]
    assert len(got) == 3 and all("реже" in i["auto_reason"] for i in got)
    await removed(4, 3)                                    # и ещё два — больше не ставим
    assert (await suggest(client, h, day(0), day(5), dry_run=True))["items"] == []

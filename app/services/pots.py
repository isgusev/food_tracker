"""Кастрюля и её резерв: все правила в одном месте.

Кастрюля (RecipeCookingLog) резервирует несъеденные порции привязанных к ней блюд плана.
- Свежая кастрюля привязывает блюда по рецепту с сегодняшнего дня, пока влезают (`attach_new`).
- Кастрюля убыла (съели больше, поправили остаток) — поздние блюда, которым не хватает, отвязываются
  и снова «надо приготовить» (`release`).
- Допуск семьи (Household.portion_tolerance, доля 0…1): вышло/осталось меньше плана не больше чем на него —
  блюда остаются привязанными, а их несъеденные порции уменьшаются пропорционально, вниз до грамма.
  Только для событий самой кастрюли (готовка, «съели», правка остатка); правки плана — без допуска:
  заданный вес порции не урезается.

Чистые функции (`remaining_weight`, `fits`, `shrink`, `fit_weights`, `scale_portions`, `set_remaining`) —
без базы; ими же пользуются покупки и автоплан.
"""
from __future__ import annotations


from datetime import date
from decimal import ROUND_FLOOR, Decimal

from app.domain import _ceil, dec, quantize
from app.models.plan import MealItem
from app.models.recipe import RecipeCookingLog
from app.repositories.plan import PlanRepository
from app.repositories.recipe import CookingLogRepository

ZERO = Decimal("0")


# ------------------------------------------------------------------ правила
def remaining_weight(item: MealItem) -> Decimal:
    """Сколько ещё не съедено по блюду (резерв кастрюли / объём покупки)."""
    return sum((dec(p.weight_g) for p in item.portions if not p.is_eaten), ZERO)


def fits(planned: Decimal, available: Decimal, tolerance: Decimal) -> bool:
    """Хватает ли: есть не меньше плана за вычетом допуска (доля 0…1)."""
    return planned * (1 - tolerance) <= available


def batches_for(need: Decimal, cooked: Decimal, allow_half: bool, tolerance: Decimal) -> Decimal:
    """Сколько закладок готовить под need граммов: вверх до целой (или половины — «можно половиной»), но на шаг
    меньше, если её не хватает в пределах допуска (`fits`): приготовят меньше, и привязанные порции уменьшатся."""
    step = Decimal("0.5") if allow_half else Decimal(1)
    batches = Decimal(_ceil(quantize(need / cooked, "0.001") / step)) * step
    if batches > step and fits(need, (batches - step) * cooked, tolerance):
        batches -= step
    return batches


def standard_portion(recipe) -> Decimal | None:
    """Порция по рецепту: выход / число порций (если порций больше одной — иначе это вся кастрюля)."""
    if recipe is None or not recipe.default_servings or recipe.default_servings < 2:
        return None
    return Decimal(str(recipe.estimated_cooked_weight)) / recipe.default_servings


def shrink(weights: dict, available: Decimal) -> dict:
    """Веса — пропорционально под то, что есть: доли сохраняются, вниз до грамма (сумма ≤ available).
    Хватает и так — без изменений."""
    total = sum(weights.values(), ZERO)
    if total <= 0 or total <= available:
        return dict(weights)
    k = max(ZERO, available) / total
    return {key: (w * k).to_integral_value(rounding=ROUND_FLOOR) for key, w in weights.items()}


def fit_weights(weights: dict, available: Decimal, tolerance: Decimal) -> dict | None:
    """Порции из кастрюли, где осталось available: не влезают с допуском — None, чуть не хватает —
    пропорционально меньше, хватает — как есть."""
    if not weights or not fits(sum(weights.values(), ZERO), available, tolerance):
        return None
    return shrink(weights, available)


def scale_portions(items: list[MealItem], available: Decimal) -> None:
    """Несъеденные порции блюд — пропорционально под то, что есть в кастрюле (съеденное не трогаем)."""
    portions = [p for i in items for p in i.portions if not p.is_eaten]
    scaled = shrink({p: dec(p.weight_g) for p in portions}, available)
    for p, w in scaled.items():
        p.weight_g = w


def set_remaining(pot: RecipeCookingLog, remainder: Decimal) -> None:
    """Новый остаток кастрюли; ноль и меньше — кастрюля пуста."""
    pot.current_remaining_weight = remainder
    pot.is_finished = remainder <= ZERO


# ------------------------------------------------------------------ сервис
class PotService:
    def __init__(self, plan: PlanRepository, cooking_logs: CookingLogRepository) -> None:
        self._plan = plan
        self._pots = cooking_logs

    async def attach_new(self, pot: RecipeCookingLog, from_date: date) -> int:
        """Свежая кастрюля: привязываем блюда её рецепта с from_date (сегодня), пока влезают.

        Прошлые неотмеченные планы кастрюлю не «съедают»; на первом не поместившемся блюде
        останавливаемся — более поздние остаются «надо приготовить» и попадают в покупки.
        «Влезает» — с допуском семьи; тогда несъеденные порции уменьшаются пропорционально выходу."""
        return await self._attach(pot, from_date, dec(pot.total_cooked_weight))

    async def attach_more(self, pot: RecipeCookingLog, from_date: date) -> int:
        """Кастрюля стала больше (поправили выход): довязываем блюда рецепта в то, что свободно сверх резерва."""
        reserved = (await self._plan.reserved_by_pot(pot.household_id)).get(pot.id, ZERO)
        return await self._attach(pot, from_date, dec(pot.current_remaining_weight) - reserved)

    async def _attach(self, pot: RecipeCookingLog, from_date: date, capacity: Decimal) -> int:
        if capacity <= 0 or pot.recipe_id is None:
            return 0
        tolerance = await self._plan.tolerance(pot.household_id)
        reserved = ZERO
        attached: list[MealItem] = []
        for item in await self._plan.unattached_for_recipe(pot.household_id, pot.recipe_id, from_date):
            need = remaining_weight(item)
            if need <= 0:
                continue  # всё уже съедено
            if not fits(reserved + need, capacity, tolerance):
                break
            reserved += need
            item.cooking_log_id = pot.id
            attached.append(item)
        if reserved > capacity:
            scale_portions(attached, capacity)
        await self._plan.flush()
        return len(attached)

    async def release(self, pot_id: int | None, *, shrink_ok: bool = False) -> int:
        """Кастрюля убыла — с конца отвязываем блюда, которым уже не хватает.

        shrink_ok — событие самой кастрюли (съели из неё, правка остатка): в пределах допуска
        блюда не отвязываются, а их несъеденные порции уменьшаются. Правки плана — без допуска."""
        if pot_id is None:
            return 0
        pot = await self._pots.get(pot_id)
        if pot is None:
            return 0
        available = dec(pot.current_remaining_weight)
        tolerance = await self._plan.tolerance(pot.household_id) if shrink_ok else ZERO
        items = await self._plan.attached_newest_first(pot.id)
        reserved = sum((remaining_weight(i) for i in items), ZERO)
        released = 0
        kept: list[MealItem] = []
        for item in items:
            need = remaining_weight(item)
            if need > 0 and not fits(reserved, available, tolerance):
                reserved -= need
                item.cooking_log_id = None
                released += 1
            else:
                kept.append(item)
        if tolerance > 0 and reserved > available:
            scale_portions(kept, available)
        await self._plan.flush()
        return released

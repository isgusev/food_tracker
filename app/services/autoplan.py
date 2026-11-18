"""Автоплан (docs/AUTOPLAN.md): предложения плана поверх обычной модели.

Этап 1 — типичные порции (3.5) и заполнение пустых ячеек тем, что уже приготовлено:
остатки в холодильнике (пока свежие) и заготовки из морозилки, которым скоро истекает срок.
Ручной план не трогаем: заполняются только ПУСТЫЕ ячейки (день + приём пищи), предложенное
помечается origin=auto с причиной; ручная правка делает его обычным (PlanService._touch).
"""
from __future__ import annotations


from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from statistics import median

from app.core import clock
from app.domain import MEAL_ORDER
from app.models.household import HouseholdMember
from app.models.plan import MealItem, MealPortion
from app.models.recipe import RecipeCookingLog
from app.repositories.household import MemberRepository
from app.repositories.plan import PlanRepository, fits
from app.core.exceptions import NotFoundError
from app.repositories.product import VariantRepository
from app.repositories.recipe import CookingLogRepository, RecipeRepository
from app.schemas.plan import AutofillPortion, AutofillSuggestion, TypicalPortion

ZERO = Decimal("0")
HISTORY_DAYS = 90
# Доля дневной цели ккал на приём пищи — когда истории порций нет (3.5)
MEAL_SHARE = {"breakfast": Decimal("0.25"), "lunch": Decimal("0.35"), "dinner": Decimal("0.30"), "snack": Decimal("0.10")}
DEFAULT_KCAL = Decimal("2000")
# Заготовку из морозилки предлагаем сама, если ей осталось не больше стольких дней
FREEZER_SOON_DAYS = 14
MIN_PORTION, MAX_PORTION = Decimal("10"), Decimal("2000")


def _round5(x: Decimal) -> Decimal:
    """Порция — до 5 г, в разумных пределах."""
    v = (x / 5).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 5
    return min(MAX_PORTION, max(MIN_PORTION, v))


def _kcal(m: HouseholdMember) -> Decimal:
    return Decimal(str(m.target_calories)) if m.target_calories else DEFAULT_KCAL


def typical_from(
    members: list[HouseholdMember],
    history: dict[int, list[Decimal]],
    meal_type: str,
    kcal_per_100g: Decimal,
    standard: Decimal | None = None,
) -> dict[int, tuple[Decimal, str]]:
    """Типичная порция каждого: медиана съеденного → по другим членам семьи пропорционально цели
    ккал → стандартная порция рецепта (выход / порций) × цель ккал / 2000 → доля цели ккал на приём
    пищи. Источник — history / family / recipe / target. Стандартная порция — раньше доли цели:
    у лёгких блюд (грибы, овощи) доля цели даёт килограммовые порции."""
    out: dict[int, tuple[Decimal, str]] = {}
    known = {m.id: Decimal(str(median(history[m.id]))) for m in members if history.get(m.id)}
    by_id = {m.id: m for m in members}
    for m in members:
        if m.id in known:
            out[m.id] = (_round5(known[m.id]), "history")
        elif known:
            ratios = [w * _kcal(m) / _kcal(by_id[o]) for o, w in known.items() if o in by_id]
            out[m.id] = (_round5(sum(ratios, ZERO) / len(ratios)), "family")
        elif standard:
            out[m.id] = (_round5(standard * _kcal(m) / DEFAULT_KCAL), "recipe")
        else:
            share = MEAL_SHARE.get(meal_type, Decimal("0.3"))
            per100 = kcal_per_100g if kcal_per_100g and kcal_per_100g > 0 else Decimal("100")
            out[m.id] = (_round5(_kcal(m) * share / per100 * 100), "target")
    return out


def standard_portion(recipe) -> Decimal | None:
    """Порция по рецепту: выход / число порций (если порций больше одной — иначе это вся кастрюля)."""
    if recipe is None or not recipe.default_servings or recipe.default_servings < 2:
        return None
    return Decimal(str(recipe.estimated_cooked_weight)) / recipe.default_servings


@dataclass
class _Board:
    """Занятость периода: ячейки (день, приём) и рецепты по дням."""

    cells: set[tuple[date, str]] = field(default_factory=set)
    recipes: set[tuple[date, int]] = field(default_factory=set)


class AutoplanService:
    def __init__(
        self, plan: PlanRepository, cooking_logs: CookingLogRepository, members: MemberRepository,
        recipes: RecipeRepository, variants: VariantRepository,
    ) -> None:
        self._plan = plan
        self._pots = cooking_logs
        self._members = members
        self._recipes = recipes
        self._variants = variants

    async def typical_for(
        self, household_id: int, meal_type: str, recipe_id: int | None, variant_id: int | None
    ) -> list[TypicalPortion]:
        """Типичные порции для формы планирования: рецепт семьи или готовый продукт."""
        if recipe_id is not None:
            recipe = await self._recipes.get(recipe_id)
            if recipe is None or recipe.household_id != household_id:
                raise NotFoundError("Рецепт не найден")
            per100 = Decimal(str(recipe.calories_per_100g))
            standard = standard_portion(recipe)
        else:
            variant = await self._variants.get(variant_id)
            if variant is None:
                raise NotFoundError("Продукт не найден")
            per100 = Decimal(str(variant.calories or 0))
            standard = None
        typical = await self.typical_portions(
            household_id, meal_type, per100, recipe_id=recipe_id, variant_id=variant_id, standard=standard
        )
        return [TypicalPortion(member_id=mid, weight_g=w, source=src) for mid, (w, src) in typical.items()]

    # ------------------------------------------------------------ типичные порции
    async def typical_portions(
        self, household_id: int, meal_type: str, kcal_per_100g: Decimal,
        *, recipe_id: int | None = None, variant_id: int | None = None, standard: Decimal | None = None,
    ) -> dict[int, tuple[Decimal, str]]:
        members = await self._members.active_in(household_id)
        since = clock.utc_now() - timedelta(days=HISTORY_DAYS)
        history: dict[int, list[Decimal]] = {}
        for member_id, w in await self._plan.eaten_weights(
            household_id, since, recipe_id=recipe_id, variant_id=variant_id
        ):
            history.setdefault(member_id, []).append(w)
        return typical_from(members, history, meal_type, kcal_per_100g, standard)

    # ------------------------------------------------- заполнение из холодильника
    async def autofill(
        self, household_id: int, user_id: int, start: date, end: date,
        meal_types: list[str] | None, dry_run: bool, today: date,
    ) -> list[AutofillSuggestion]:
        first = max(start, today)
        if first > end:
            return []
        wanted = [m for m in MEAL_ORDER if meal_types is None or m in meal_types]
        board = _Board()
        for item in await self._plan.list_in_range(household_id, first, end):
            board.cells.add((item.date_day, item.meal_type))
            if item.recipe_id is not None:
                board.recipes.add((item.date_day, item.recipe_id))

        tolerance = await self._plan.tolerance(household_id)
        reserved = await self._plan.reserved_by_pot(household_id)
        pots = await self._pots.active_with_recipe(household_id)
        fridge = sorted((p for p in pots if not p.is_frozen), key=lambda p: (p.good_until, p.id))
        freezer = sorted(
            (p for p in pots if p.is_frozen and p.good_until <= today + timedelta(days=FREEZER_SOON_DAYS)),
            key=lambda p: (p.good_until, p.id),
        )
        out: list[AutofillSuggestion] = []
        for pot in fridge + freezer:
            free = Decimal(str(pot.current_remaining_weight)) - reserved.get(pot.id, ZERO)
            out += await self._place_pot(household_id, user_id, pot, free, first, end, wanted, board, tolerance, dry_run)
        if not dry_run:
            await self._plan.flush()
        return out

    async def _place_pot(
        self, household_id: int, user_id: int, pot: RecipeCookingLog, free: Decimal,
        first: date, end: date, wanted: list[str], board: _Board, tolerance: Decimal, dry_run: bool,
    ) -> list[AutofillSuggestion]:
        recipe = pot.recipe
        meals = [m for m in (recipe.meal_types or MEAL_ORDER) if m in wanted]   # NULL — любой приём
        last = min(end, pot.good_until)
        reason = (
            f"заготовка в морозилке, годна до {pot.good_until:%d.%m}" if pot.is_frozen
            else f"остаток в холодильнике, съесть до {pot.good_until:%d.%m}"
        )
        per100 = Decimal(str(pot.calories_per_100g))
        typical: dict[str, dict[int, tuple[Decimal, str]]] = {}
        out: list[AutofillSuggestion] = []
        day = first
        while day <= last and free > 0:
            if (day, recipe.id) in board.recipes:   # одно блюдо — не дважды за день
                day += timedelta(days=1)
                continue
            for meal in meals:
                if (day, meal) in board.cells:
                    continue
                if meal not in typical:
                    typical[meal] = await self.typical_portions(
                        household_id, meal, per100, recipe_id=recipe.id, standard=standard_portion(recipe)
                    )
                weights = {mid: w for mid, (w, _) in typical[meal].items()}
                need = sum(weights.values(), ZERO)
                if not weights or not fits(need, free, tolerance):
                    return out          # дальше в этой кастрюле не хватит
                if need > free:          # чуть меньше нужного — порции пропорционально (допуск)
                    k = free / need
                    weights = {mid: (w * k).to_integral_value(rounding=ROUND_FLOOR) for mid, w in weights.items()}
                    need = sum(weights.values(), ZERO)
                free -= need
                board.cells.add((day, meal))
                board.recipes.add((day, recipe.id))
                item_id = None
                if not dry_run:
                    item = MealItem(
                        household_id=household_id, date_day=day, meal_type=meal, recipe_id=recipe.id,
                        cooking_log_id=pot.id, origin="auto", auto_reason=reason, created_by_user_id=user_id,
                        portions=[MealPortion(member_id=mid, weight_g=w) for mid, w in weights.items()],
                    )
                    self._plan.add(item)
                    await self._plan.flush()
                    item_id = item.id
                out.append(AutofillSuggestion(
                    date_day=day, meal_type=meal, recipe_id=recipe.id, name=recipe.name, cooking_log_id=pot.id,
                    portions=[AutofillPortion(member_id=mid, weight_g=w) for mid, w in weights.items()],
                    auto_reason=reason, item_id=item_id,
                ))
                break   # следующий день
            day += timedelta(days=1)
        return out

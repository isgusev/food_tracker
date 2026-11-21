"""Автоплан (docs/AUTOPLAN.md): предложения плана поверх обычной модели.

Шаги генерации (4.1): 1) остатки в холодильнике (пока свежие) и заготовки из морозилки — те, которым
скоро истекает срок, и любые в дни «без готовки»; 2) регулярные готовые продукты (этап 3): продукт, который
в этот день недели и приём пищи стоял в ≥ 4 из 8 последних недель, — в пустую ячейку (если ели его там без
блюда) или добавкой к предложенному блюду (если ели вместе с блюдом);
3) готовки: в каждую пустую ячейку — лучший по оценке (4.2) рецепт в ротации, его закладка закрывает
тот же приём следующих дней в пределах keeps_days и выхода; 4) оценки пересчитываются после каждого
выбора; 5) порции — типичные (3.5).

Ручной план не трогаем: заполняются только ПУСТЫЕ ячейки, предложенное — origin=auto с причиной;
повторная генерация заменяет только auto без 📌, без кастрюли и без съеденного. Ручная правка
делает блюдо обычным (PlanService._touch).
"""
from __future__ import annotations


import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.core import clock
from app.domain import MEAL_ORDER, monday
from app.models.household import HouseholdMember
from app.models.plan import MealItem, MealPortion
from app.models.recipe import RecipeCookingLog
from app.repositories.household import MemberRepository
from app.repositories.plan import PlanRepository
from app.services.pots import fit_weights, standard_portion
from app.core.exceptions import NotFoundError, ValidationError
from app.models.recipe import Recipe
from app.repositories.household import HouseholdRepository
from app.repositories.stock import StockRepository
from app.services.finance import FinanceService
from app.services.household import planner_out
from app.services.naming import display_name
from app.repositories.product import VariantRepository
from app.repositories.recipe import CookingLogRepository, RecipeRepository
from app.schemas.plan import AutofillOut, AutofillPortion, AutofillSuggestion, TypicalPortion

ZERO = Decimal("0")
HISTORY_DAYS = 90
# Доля дневной цели ккал на приём пищи — когда истории порций нет (3.5)
MEAL_SHARE = {"breakfast": Decimal("0.25"), "lunch": Decimal("0.35"), "dinner": Decimal("0.30"), "snack": Decimal("0.10")}
DEFAULT_KCAL = Decimal("2000")
# Заготовку из морозилки предлагаем сама, если ей осталось не больше стольких дней
FREEZER_SOON_DAYS = 14
MIN_PORTION, MAX_PORTION = Decimal("10"), Decimal("2000")

# Оценка блюда (4.2): веса составляющих
W_REST = 1.0      # давно не готовили (насыщение к 14 дням)
W_EXPIRY = 0.8    # доля состава из запасов, которым срок ≤ 3 дней
W_SHARE = 0.4     # доля товаров, общих с уже выбранными на период
W_COST = 0.5      # дороже средней порции — минус, если бюджет месяца тратится быстрее срока
W_KBJU = 0.3      # закрывает белок по целям едоков
W_SPECIAL = 0.5   # «эдакое» в отмеченный для него день
REPEAT_PENALTY = 1.0   # то же блюдо в последние 2 дня
W_FB = 0.5        # отзывы семьи (этап 4): 📌 и ✓ — плюс, 🔄 и ✕ — минус
W_POP = 0.6       # любимое: в скольких из 8 последних недель блюдо было в плане (ставили сами или ели)
FEEDBACK_WEIGHT = {"pinned": 1.0, "accepted": 0.5, "replaced": -0.7, "removed": -1.0}
FEEDBACK_HALF_LIFE = 30    # дней: отзыв вдвое слабее через месяц
FEEDBACK_DAYS = 120        # старше — не учитываем
FEEDBACK_CAP = 2.0
PRODUCT_RARER = -1.5       # обычный продукт: два «убрать» — предлагаем реже (через неделю / через день)
PRODUCT_DISLIKED = -3.0    # и ещё два — не ставим (отзывы затухают, со временем вернётся)
ITEM_FEEDBACK_CAP = 4.0
DAILY_MIN_PER_WEEK = 4     # продукт в этом приёме ≥ 4 дней в неделю в среднем — привычка «каждый день»
REST_DAYS = 14
EXPIRY_DAYS = 3
CONTINUE_PREFIX = "та же закладка"
REGULAR_WEEKS = 8
REGULAR_MIN_WEEKS = 4
WEEKDAYS_PL = ("по понедельникам", "по вторникам", "по средам", "по четвергам", "по пятницам",
               "по субботам", "по воскресеньям")
MEAL_NA = {"breakfast": "на завтрак", "lunch": "на обед", "dinner": "на ужин", "snack": "на перекус"}
MEAL_K = {"breakfast": "к завтраку", "lunch": "к обеду", "dinner": "к ужину", "snack": "к перекусу"}


@dataclass
class _Regular:
    """Регулярный готовый продукт в ячейке (день недели + приём пищи)."""

    weekday: int | None                         # None — каждый день (привычка)
    meal: str
    item_key: str
    variant_id: int
    name: str
    side: bool                                  # True — к блюду, False — сам по себе
    weights: dict[int, Decimal]                 # член семьи → обычная порция
    rare: bool = False                          # семья его убирала — предлагаем реже

    def due(self, day: date) -> bool:
        """Ставить ли в этот день: свой день недели (или каждый); «реже» — через неделю / через день."""
        if self.weekday is not None and self.weekday != day.weekday():
            return False
        if not self.rare:
            return True
        return day.isocalendar()[1] % 2 == 0 if self.weekday is not None else day.toordinal() % 2 == 0

    def reason(self) -> str:
        meal = MEAL_K[self.meal] if self.side else MEAL_NA[self.meal]
        when = f" {WEEKDAYS_PL[self.weekday]}" if self.weekday is not None else ""
        return f"обычно {meal}{when}" + (" (реже: вы его убирали)" if self.rare else "")


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
    """Типичная порция каждого: своя медиана съеденного (так человек ест на самом деле — в том числе после
    ручных правок) → одна порция рецепта (выход / порций) → медиана съеденного другими членами семьи → доля
    цели ккал на приём пищи. Источник — history / recipe / family / target. Цель ккал размер порции блюда
    не меняет (решение Ивана 21.11): каждому по порции, кто ест меньше — правит вручную, и это запоминается
    историей. Доля цели остаётся последним запасным вариантом — для готовых продуктов и рецептов без порций."""
    out: dict[int, tuple[Decimal, str]] = {}
    known = {m.id: Decimal(str(median(history[m.id]))) for m in members if history.get(m.id)}
    for m in members:
        if m.id in known:
            out[m.id] = (_round5(known[m.id]), "history")
        elif standard:
            out[m.id] = (_round5(standard), "recipe")
        elif known:
            out[m.id] = (_round5(Decimal(str(median(known.values())))), "family")
        else:
            share = MEAL_SHARE.get(meal_type, Decimal("0.3"))
            per100 = kcal_per_100g if kcal_per_100g and kcal_per_100g > 0 else Decimal("100")
            out[m.id] = (_round5(_kcal(m) * share / per100 * 100), "target")
    return out


_monday = monday


def _keys(recipe: Recipe) -> dict[str, str]:
    """Товары состава рецепта: item_key → название (для причины)."""
    out: dict[str, str] = {}
    for ing in recipe.template_ingredients:
        product = ing.variant.manufacturer.product if ing.variant and ing.variant.manufacturer else None
        if product is not None and product.item_key:
            out.setdefault(product.item_key, product.name)
    return out


def allowed_meals(recipe: Recipe) -> list[str]:
    """Уместные приёмы пищи; NULL — любой (решение 19.11)."""
    return list(recipe.meal_types or MEAL_ORDER)


@dataclass
class _Board:
    """Занятость периода: ячейки (день, приём), рецепты по дням и «эдакое» по неделям."""

    cells: set[tuple[date, str]] = field(default_factory=set)
    recipes: set[tuple[date, int]] = field(default_factory=set)
    recipe_days: dict[int, set[date]] = field(default_factory=dict)
    special_weeks: dict[date, int] = field(default_factory=dict)
    chosen_keys: dict[str, dict[int, str]] = field(default_factory=dict)   # товар → {рецепт: название}

    def put(self, day: date, meal: str, recipe: Recipe | None, keys: dict[str, str] | None = None,
            count_special: bool = True) -> None:
        self.cells.add((day, meal))
        if recipe is None:
            return
        self.recipes.add((day, recipe.id))
        self.recipe_days.setdefault(recipe.id, set()).add(day)
        if count_special and recipe.effort == "special":
            w = _monday(day)
            self.special_weeks[w] = self.special_weeks.get(w, 0) + 1
        for k in (keys or {}):
            self.chosen_keys.setdefault(k, {})[recipe.id] = recipe.name


def feedback_scores(rows, today: date, item_cap: float = ITEM_FEEDBACK_CAP) -> tuple[dict[int, float], dict[str, float]]:
    """Сумма отзывов с затуханием (вдвое за FEEDBACK_HALF_LIFE дней), по рецептам и по товарам готовых
    продуктов, в пределах ±FEEDBACK_CAP. Одинаковые отзывы об одном за день — один (закладка на три дня,
    «Убрать» всех её дней — не тройной минус)."""
    seen: set = set()
    recipes: dict[int, float] = {}
    items: dict[str, float] = {}
    for f in rows:
        target, key = (recipes, f.recipe_id) if f.recipe_id is not None else (items, f.item_key)
        if key is None or f.action not in FEEDBACK_WEIGHT:
            continue
        day = clock.local_date(f.created_at)
        if (key, f.action, day) in seen:
            continue
        seen.add((key, f.action, day))
        age = max(0, (today - day).days)
        target[key] = target.get(key, 0.0) + FEEDBACK_WEIGHT[f.action] * 0.5 ** (age / FEEDBACK_HALF_LIFE)
    clamp = lambda d, cap: {k: max(-cap, min(cap, v)) for k, v in d.items()}
    return clamp(recipes, FEEDBACK_CAP), clamp(items, item_cap)


@dataclass
class Scoring:
    """Данные для оценки блюда (4.2): не зависят от БД — тестируются отдельно."""

    keys: dict[int, dict[str, str]]                 # рецепт → товары состава
    last_cooked: dict[int, date]                    # рецепт → последняя готовка/план до периода
    expiring: dict[str, tuple[date, str]]           # товар → (срок, название) запасов
    cost: dict[int, Decimal] = field(default_factory=dict)   # рецепт → цена порции
    budget_tight: bool = False
    protein_target: float = 0.15                    # доля ккал из белка в целях едоков
    special_days: set[int] = field(default_factory=set)
    feedback: dict[int, float] = field(default_factory=dict)   # рецепт → сумма отзывов семьи
    popular: dict[int, float] = field(default_factory=dict)    # рецепт → доля недель с ним в плане (0…1)

    def score(self, recipe: Recipe, day: date, board: _Board) -> tuple[float, str]:
        """Оценка и причина выбора: истекающий срок продукта, если он есть, иначе самая весомая
        положительная составляющая."""
        parts: list[tuple[float, str]] = []   # (вклад, причина); причина "" — не объясняет выбор
        urgent = ""
        # давно не готовили: последняя готовка до периода или блюдо раньше в этом плане
        before = [d for d in board.recipe_days.get(recipe.id, ()) if d < day]
        last = max(before + ([self.last_cooked[recipe.id]] if recipe.id in self.last_cooked else []), default=None)
        if last is None:
            parts.append((W_REST, "давно не было в плане"))
        else:
            gap = (day - last).days
            parts.append((W_REST * min(gap / REST_DAYS, 1.0), f"не готовили {gap} дн"))
        keys = self.keys.get(recipe.id, {})
        if keys:
            exp = [self.expiring[k] for k in keys
                   if k in self.expiring and day <= self.expiring[k][0] <= day + timedelta(days=EXPIRY_DAYS)]
            if exp:
                until, name = min(exp)
                urgent = f"{name.lower()} до {until:%d.%m}"
                parts.append((W_EXPIRY * len(exp) / len(keys), urgent))
            # общие товары — только с ДРУГИМИ блюдами периода
            others = {k: [n for rid, n in board.chosen_keys.get(k, {}).items() if rid != recipe.id] for k in keys}
            shared = [k for k, names in others.items() if names]
            if shared:
                parts.append((W_SHARE * len(shared) / len(keys), f"общий товар с «{others[shared[0]][0]}»"))
        if self.budget_tight and recipe.id in self.cost:
            avg = sum(self.cost.values(), ZERO) / len(self.cost)
            if avg > 0 and self.cost[recipe.id] > avg:
                parts.append((-W_COST * float((self.cost[recipe.id] - avg) / avg), ""))
        kcal = float(recipe.calories_per_100g or 0)
        if kcal > 0 and self.protein_target > 0:
            share = float(recipe.proteins_per_100g or 0) * 4 / kcal
            parts.append((W_KBJU * min(share / self.protein_target, 1.0), "белок по целям"))
        if recipe.effort == "special" and day.weekday() in self.special_days:
            parts.append((W_SPECIAL, "день для особого блюда"))
        pop = self.popular.get(recipe.id, 0.0)
        if pop:
            parts.append((W_POP * pop, "часто готовите"))
        fb = self.feedback.get(recipe.id, 0.0)
        if fb:
            parts.append((W_FB * fb, "семья часто выбирает" if fb > 0 else ""))
        if any(day - timedelta(days=k) in board.recipe_days.get(recipe.id, ()) for k in (1, 2)):
            parts.append((-REPEAT_PENALTY, ""))
        total = sum(p for p, _ in parts)
        reasons = [(p, r) for p, r in parts if r and p > 0]
        reason = urgent or (max(reasons, key=lambda x: x[0])[1] if reasons else "в ротации")
        return total, reason


@dataclass
class _Ctx:
    """Всё для генерации на период: настройки, рецепты, доска, оценка."""

    household_id: int
    user_id: int
    first: date
    end: date
    wanted: list[str]
    no_cook: set[int]
    special_days: set[int]
    max_special: int
    tolerance: Decimal
    rotation: list[Recipe]
    scoring: Scoring
    board: _Board
    dry_run: bool
    typical: dict[tuple[int, str], dict[int, tuple[Decimal, str]]] = field(default_factory=dict)
    products: set[tuple[date, str, str]] = field(default_factory=set)   # (день, приём, товар) — уже стоит
    item_feedback: dict[str, float] = field(default_factory=dict)       # товар → сумма отзывов
    history: list = field(default_factory=list)                          # план 8 недель до периода
    regular_cells: set[tuple[date, str]] = field(default_factory=set)   # ячейки, занятые регулярными продуктами


class AutoplanService:
    def __init__(
        self, plan: PlanRepository, cooking_logs: CookingLogRepository, members: MemberRepository,
        recipes: RecipeRepository, variants: VariantRepository,
        households: HouseholdRepository, stock: StockRepository, finance: FinanceService,
    ) -> None:
        self._plan = plan
        self._pots = cooking_logs
        self._members = members
        self._recipes = recipes
        self._variants = variants
        self._households = households
        self._stock = stock
        self._finance = finance
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

    # ------------------------------------------------------------- генерация
    async def _context(
        self, household_id: int, user_id: int, first: date, end: date,
        meal_types: list[str] | None, dry_run: bool, today: date,
    ) -> _Ctx:
        settings = planner_out(await self._households.planner(household_id))
        wanted_set = set(meal_types or MEAL_ORDER)
        if settings.meal_types and meal_types is None:
            wanted_set &= set(settings.meal_types)
        recipes = await self._recipes.list_full(household_id=household_id, limit=2000)
        keys = {r.id: _keys(r) for r in recipes}
        last = await self._plan.last_recipe_dates(household_id, first)
        for rid, d in (await self._pots.last_cooked(household_id)).items():
            if d < first:
                last[rid] = max(d, last.get(rid, d))
        expiring: dict[str, tuple[date, str]] = {}
        horizon = end + timedelta(days=EXPIRY_DAYS)
        for lot in await self._stock.open_lots(household_id):
            if lot.expires_on is None or not (today <= lot.expires_on <= horizon):
                continue
            k = lot.product.item_key
            if k not in expiring or lot.expires_on < expiring[k][0]:
                expiring[k] = (lot.expires_on, lot.product.name)
        cost = {c.recipe_id: c.per_portion for c in await self._finance.recipe_costs(household_id)
                if c.per_portion is not None}
        tight = await self._budget_tight(household_id, today)
        rows = await self._plan.feedback_since(household_id, clock.utc_now() - timedelta(days=FEEDBACK_DAYS))
        recipe_fb, item_fb = feedback_scores(rows, today)
        # план 8 недель до периода: ручное и съеденное (непринятые предложения — не история)
        w0 = _monday(first) - timedelta(weeks=REGULAR_WEEKS)
        history = [i for i in await self._plan.list_in_range(household_id, w0, first - timedelta(days=1))
                   if i.origin != "auto" or any(p.is_eaten for p in i.portions)]
        weeks: dict[int, set[int]] = {}
        for i in history:
            if i.recipe_id is not None:
                weeks.setdefault(i.recipe_id, set()).add((i.date_day - w0).days // 7)
        popular = {rid: len(w) / REGULAR_WEEKS for rid, w in weeks.items()}
        members = await self._members.active_in(household_id)
        shares = [float(m.target_proteins) * 4 / float(m.target_calories)
                  for m in members if m.target_proteins and m.target_calories]
        scoring = Scoring(
            keys=keys, last_cooked=last, expiring=expiring, cost=cost, budget_tight=tight,
            protein_target=sum(shares) / len(shares) if shares else 0.15,
            special_days=set(settings.special_days),
            feedback=recipe_fb, popular=popular,
        )
        return _Ctx(
            household_id=household_id, user_id=user_id, first=first, end=end,
            wanted=[m for m in MEAL_ORDER if m in wanted_set],
            no_cook=set(settings.no_cook_days),
            special_days=scoring.special_days,
            max_special=settings.max_special_per_week,
            tolerance=await self._plan.tolerance(household_id),
            rotation=[r for r in recipes if r.in_rotation],
            scoring=scoring, board=_Board(), dry_run=dry_run, item_feedback=item_fb, history=history,
        )

    async def _budget_tight(self, household_id: int, today: date) -> bool:
        """Бюджет месяца тратится быстрее, чем идёт месяц (траты / бюджет > прошедшая доля месяца)."""
        household = await self._households.get(household_id)
        if household is None or not household.monthly_budget:
            return False
        month_start = today.replace(day=1)
        spent = await self._stock.spent_between(household_id, month_start, today)
        days = calendar.monthrange(today.year, today.month)[1]
        return spent / Decimal(str(household.monthly_budget)) > Decimal(today.day) / days

    @staticmethod
    def _replaceable(item: MealItem) -> bool:
        """Прежнее предложение, которое перегенерация может заменить."""
        return (
            item.origin == "auto" and not item.pinned and item.cooking_log_id is None
            and not any(p.is_eaten for p in item.portions)
        )

    async def autofill(
        self, household_id: int, user_id: int, start: date, end: date,
        meal_types: list[str] | None, dry_run: bool, today: date, cook: bool = True,
    ) -> AutofillOut:
        first = max(start, today)
        if first > end:
            return AutofillOut(items=[], dry_run=dry_run)
        ctx = await self._context(household_id, user_id, first, end, meal_types, dry_run, today)
        # соседние дни (до периода и внутри) — для повторов, «эдакого» за неделю и общих товаров
        replaced = 0
        for item in await self._plan.list_in_range(household_id, _monday(first) - timedelta(days=2), end):
            if (first <= item.date_day and item.meal_type in ctx.wanted and cook
                    and self._replaceable(item)):
                replaced += 1
                if not dry_run:
                    await self._plan.delete(item)
                continue
            if item.date_day >= first:
                ctx.board.cells.add((item.date_day, item.meal_type))
                if item.variant is not None and item.variant.manufacturer is not None:
                    ctx.products.add((item.date_day, item.meal_type, item.variant.manufacturer.product.item_key))
            if item.recipe is not None:
                ctx.board.put(item.date_day, item.meal_type, item.recipe, ctx.scoring.keys.get(item.recipe_id))
        if not dry_run and replaced:
            await self._plan.flush()
        # put() добавил и ячейки до периода — они не мешают: генерация идёт с first

        out = await self._fill_from_pots(ctx, today)
        regs = await self._regulars(ctx)
        out += await self._fill_regular(ctx, regs)
        if cook:
            out += await self._fill_cooking(ctx)
        out += await self._fill_sides(ctx, regs, out)
        if not dry_run:
            await self._plan.flush()
        out.sort(key=lambda s: (s.date_day, MEAL_ORDER.index(s.meal_type)))
        return AutofillOut(items=out, replaced=replaced, dry_run=dry_run)

    async def _fill_from_pots(self, ctx: _Ctx, today: date) -> list[AutofillSuggestion]:
        reserved = await self._plan.reserved_by_pot(ctx.household_id)
        pots = await self._pots.active_with_recipe(ctx.household_id)
        fridge = sorted((p for p in pots if not p.is_frozen), key=lambda p: (p.good_until, p.id))
        soon = today + timedelta(days=FREEZER_SOON_DAYS)
        freezer = sorted((p for p in pots if p.is_frozen), key=lambda p: (p.good_until, p.id))
        out: list[AutofillSuggestion] = []
        for pot in fridge + freezer:
            free = Decimal(str(pot.current_remaining_weight)) - reserved.get(pot.id, ZERO)
            # заготовка: скоро истекает — в любой день, иначе только в дни «без готовки»
            only = None if (not pot.is_frozen or pot.good_until <= soon) else ctx.no_cook
            if only is not None and not only:
                continue
            out += await self._place_pot(ctx, pot, free, only)
        return out

    async def _typical(self, ctx: _Ctx, recipe: Recipe, meal: str, per100: Decimal) -> dict[int, Decimal]:
        key = (recipe.id, meal)
        if key not in ctx.typical:
            ctx.typical[key] = await self.typical_portions(
                ctx.household_id, meal, per100, recipe_id=recipe.id, standard=standard_portion(recipe)
            )
        return {mid: w for mid, (w, _) in ctx.typical[key].items()}

    async def _add_item(
        self, ctx: _Ctx, day: date, meal: str, recipe: Recipe, weights: dict[int, Decimal],
        reason: str, source: str, pot_id: int | None = None,
    ) -> AutofillSuggestion:
        item_id = None
        if not ctx.dry_run:
            item = MealItem(
                household_id=ctx.household_id, date_day=day, meal_type=meal, recipe_id=recipe.id,
                cooking_log_id=pot_id, origin="auto", auto_reason=reason[:200], created_by_user_id=ctx.user_id,
                portions=[MealPortion(member_id=mid, weight_g=w) for mid, w in weights.items()],
            )
            self._plan.add(item)
            await self._plan.flush()
            item_id = item.id
        return AutofillSuggestion(
            date_day=day, meal_type=meal, recipe_id=recipe.id, name=recipe.name, cooking_log_id=pot_id,
            portions=[AutofillPortion(member_id=mid, weight_g=w) for mid, w in weights.items()],
            auto_reason=reason, source=source, item_id=item_id,
        )

    async def _place_pot(
        self, ctx: _Ctx, pot: RecipeCookingLog, free: Decimal, only_weekdays: set[int] | None,
    ) -> list[AutofillSuggestion]:
        recipe = pot.recipe
        meals = [m for m in allowed_meals(recipe) if m in ctx.wanted]
        last = min(ctx.end, pot.good_until)
        reason = (
            f"заготовка в морозилке, годна до {pot.good_until:%d.%m}" if pot.is_frozen
            else f"остаток в холодильнике, съесть до {pot.good_until:%d.%m}"
        )
        per100 = Decimal(str(pot.calories_per_100g))
        out: list[AutofillSuggestion] = []
        day = ctx.first
        while day <= last and free > 0:
            if (day, recipe.id) in ctx.board.recipes or (
                only_weekdays is not None and day.weekday() not in only_weekdays
            ):
                day += timedelta(days=1)
                continue
            for meal in meals:
                if (day, meal) in ctx.board.cells:
                    continue
                # чуть меньше нужного — порции пропорционально (допуск семьи), совсем не хватает — стоп
                weights = fit_weights(await self._typical(ctx, recipe, meal, per100), free, ctx.tolerance)
                if weights is None:
                    return out          # дальше в этой кастрюле не хватит
                free -= sum(weights.values(), ZERO)
                ctx.board.put(day, meal, recipe, count_special=False)
                out.append(await self._add_item(
                    ctx, day, meal, recipe, weights, reason, "freezer" if pot.is_frozen else "fridge", pot.id))
                break   # следующий день
            day += timedelta(days=1)
        return out

    def _candidates(self, ctx: _Ctx, day: date, meal: str) -> list[tuple[float, Recipe, str]]:
        """Рецепты, уместные в ячейке, по убыванию оценки (при равенстве — по id)."""
        out = []
        week = _monday(day)
        for r in ctx.rotation:
            if meal not in allowed_meals(r) or (day, r.id) in ctx.board.recipes:
                continue
            if r.effort == "special":
                if ctx.board.special_weeks.get(week, 0) >= ctx.max_special:
                    continue
                if ctx.special_days and day.weekday() not in ctx.special_days:
                    continue
            score, reason = ctx.scoring.score(r, day, ctx.board)
            out.append((score, r, reason))
        out.sort(key=lambda x: (-x[0], x[1].id))
        return out

    async def _cook_at(
        self, ctx: _Ctx, day: date, meal: str, recipe: Recipe, reason: str,
    ) -> list[AutofillSuggestion]:
        """Готовка в ячейке + та же закладка в тот же приём следующих дней (keeps_days, выход)."""
        per100 = Decimal(str(recipe.calories_per_100g))
        weights = await self._typical(ctx, recipe, meal, per100)
        if not weights:
            return []
        ctx.board.put(day, meal, recipe, ctx.scoring.keys.get(recipe.id))
        out = [await self._add_item(ctx, day, meal, recipe, weights, reason, "cook")]
        batch = Decimal(str(recipe.estimated_cooked_weight or 0))
        used = sum(weights.values(), ZERO)
        for k in range(1, max(1, recipe.keeps_days or 2)):
            d = day + timedelta(days=k)
            if d > ctx.end or (d, meal) in ctx.board.cells or (d, recipe.id) in ctx.board.recipes:
                break
            more = await self._typical(ctx, recipe, meal, per100)
            need = sum(more.values(), ZERO)
            if used + need > batch:      # закладки не хватит — дальше готовим заново
                break
            used += need
            ctx.board.put(d, meal, recipe, count_special=False)
            out.append(await self._add_item(
                ctx, d, meal, recipe, more, f"{CONTINUE_PREFIX} от {day:%d.%m}", "continue"))
        return out

    async def _fill_cooking(self, ctx: _Ctx) -> list[AutofillSuggestion]:
        out: list[AutofillSuggestion] = []
        day = ctx.first
        while day <= ctx.end:
            if day.weekday() not in ctx.no_cook:
                for meal in ctx.wanted:
                    if (day, meal) in ctx.board.cells:
                        continue
                    cands = self._candidates(ctx, day, meal)
                    if cands:
                        _, recipe, reason = cands[0]
                        out += await self._cook_at(ctx, day, meal, recipe, reason)
            day += timedelta(days=1)
        return out

    # ------------------------------------------------- регулярные продукты
    async def _regulars(self, ctx: _Ctx) -> list[_Regular]:
        """Обычные готовые продукты по плану 8 недель до периода (ручное и съеденное):
        - тот же день недели и приём пищи ≥ 4 недель из 8 — в этот день недели;
        - в этом приёме пищи ≥ 4 дней в неделю в среднем — каждый день (привычка);
        «сам по себе» (ели без блюда) — в пустую ячейку, «к блюду» — к предложенному блюду.
        «Никогда» у товара — не предлагаем; отзывы: два «убрать» — реже, ещё два — не ставим."""
        w0 = _monday(ctx.first) - timedelta(weeks=REGULAR_WEEKS)
        # «в неделю» — по реальному сроку истории (семья могла начать вести план недавно), не больше 8 недель
        start = min((i.date_day for i in ctx.history), default=w0)
        span_weeks = max(1.0, (ctx.first - max(w0, start)).days / 7)
        with_recipe = {(i.date_day, i.meal_type) for i in ctx.history if i.recipe_id is not None}
        never = {k for k, st in (await self._stock.settings_map(ctx.household_id)).items()
                 if st.regular == "never"}
        active = {m.id for m in await self._members.active_in(ctx.household_id)}

        def new_group(it):
            return {"alone": set(), "side": set(), "n": 0, "who": {}, "variant": it.variant_id, "last": it.date_day,
                    "name": display_name(it.variant, it.variant_id)}

        by_weekday: dict[tuple[int, str, str], dict] = {}
        by_meal: dict[tuple[str, str], dict] = {}
        for it in ctx.history:
            if it.variant_id is None or it.variant is None:
                continue
            product = it.variant.manufacturer.product if it.variant.manufacturer else None
            if product is None or product.item_key in never \
                    or ctx.item_feedback.get(product.item_key, 0.0) <= PRODUCT_DISLIKED:
                continue                     # «не предлагать» или семья его стабильно убирает
            side = (it.date_day, it.meal_type) in with_recipe
            for g, mark in ((by_weekday.setdefault((it.date_day.weekday(), it.meal_type, product.item_key), new_group(it)),
                             (it.date_day - w0).days // 7),
                            (by_meal.setdefault((it.meal_type, product.item_key), new_group(it)), it.date_day)):
                g["side" if side else "alone"].add(mark)
                g["n"] += 1
                if it.date_day >= g["last"]:
                    g["variant"], g["last"] = it.variant_id, it.date_day
                    g["name"] = display_name(it.variant, it.variant_id)
                for p in it.portions:
                    if p.member_id in active:
                        g["who"].setdefault(p.member_id, []).append(Decimal(str(p.weight_g)))

        def weights_of(g):
            return {mid: _round5(Decimal(str(median(ws)))) for mid, ws in g["who"].items()
                    if len(ws) * 2 >= g["n"]}   # тот, кто ест его хотя бы в половине случаев

        out: list[_Regular] = []
        daily: set[tuple[str, str]] = set()
        for (meal, key), g in sorted(by_meal.items()):
            alone, side = len(g["alone"]), len(g["side"])
            if (alone + side) / span_weeks >= DAILY_MIN_PER_WEEK and (w := weights_of(g)):
                daily.add((meal, key))
                out.append(_Regular(None, meal, key, g["variant"], g["name"], side > alone, w,
                                    rare=ctx.item_feedback.get(key, 0.0) <= PRODUCT_RARER))
        for (wd, meal, key), g in sorted(by_weekday.items()):
            alone, side = len(g["alone"]), len(g["side"])
            if (meal, key) in daily or max(alone, side) < REGULAR_MIN_WEEKS:
                continue
            if w := weights_of(g):
                out.append(_Regular(wd, meal, key, g["variant"], g["name"], side > alone, w,
                                    rare=ctx.item_feedback.get(key, 0.0) <= PRODUCT_RARER))
        return out

    async def _add_product(self, ctx: _Ctx, day: date, reg: _Regular, reason: str, source: str) -> AutofillSuggestion:
        ctx.products.add((day, reg.meal, reg.item_key))
        item_id = None
        if not ctx.dry_run:
            item = MealItem(
                household_id=ctx.household_id, date_day=day, meal_type=reg.meal, variant_id=reg.variant_id,
                origin="auto", auto_reason=reason, created_by_user_id=ctx.user_id,
                portions=[MealPortion(member_id=mid, weight_g=w) for mid, w in reg.weights.items()],
            )
            self._plan.add(item)
            await self._plan.flush()
            item_id = item.id
        return AutofillSuggestion(
            date_day=day, meal_type=reg.meal, variant_id=reg.variant_id, name=reg.name,
            portions=[AutofillPortion(member_id=mid, weight_g=w) for mid, w in reg.weights.items()],
            auto_reason=reason, source=source, item_id=item_id,
        )

    async def _fill_regular(self, ctx: _Ctx, regs: list[_Regular]) -> list[AutofillSuggestion]:
        """Шаг 2: продукт «сам по себе» — в пустую ячейку своего дня недели (или каждого дня)."""
        out = []
        day = ctx.first
        while day <= ctx.end:
            for reg in regs:
                if reg.side or not reg.due(day) or reg.meal not in ctx.wanted:
                    continue
                if (day, reg.meal) in ctx.board.cells and (day, reg.meal) not in ctx.regular_cells:
                    continue                 # занято блюдом или ручным планом
                if (day, reg.meal, reg.item_key) in ctx.products:
                    continue
                ctx.board.cells.add((day, reg.meal))
                ctx.regular_cells.add((day, reg.meal))
                out.append(await self._add_product(ctx, day, reg, reg.reason(), "regular"))
            day += timedelta(days=1)
        return out

    async def _fill_sides(self, ctx: _Ctx, regs: list[_Regular], placed: list[AutofillSuggestion]) -> list[AutofillSuggestion]:
        """Продукт «к блюду» — в ячейки, куда автоплан только что поставил блюдо."""
        out = []
        cells = sorted({(s.date_day, s.meal_type) for s in placed if s.recipe_id is not None},
                       key=lambda c: (c[0], MEAL_ORDER.index(c[1])))
        for day, meal in cells:
            for reg in regs:
                if not reg.side or not reg.due(day) or reg.meal != meal:
                    continue
                if (day, meal, reg.item_key) in ctx.products:
                    continue
                out.append(await self._add_product(ctx, day, reg, reg.reason(), "side"))
        return out

    # ------------------------------------------------------- другой вариант
    async def alternative(self, item: MealItem, user_id: int, today: date) -> int | None:
        """🔄 Следующий по оценке рецепт на ту же ячейку (по кругу, без повторов подряд).
        Та же закладка на следующие дни заменяется вместе с ним."""
        if item.recipe_id is None:
            raise ValidationError("Другой вариант — только для блюд по рецепту")
        if item.cooking_log_id is not None or any(p.is_eaten for p in item.portions):
            raise ValidationError("Блюдо уже приготовлено или съедено — замените его вручную")
        day, meal, current = item.date_day, item.meal_type, item.recipe_id
        ctx = await self._context(item.household_id, user_id, day, day + timedelta(days=14), [meal], False, today)
        keeps = item.recipe.keeps_days if item.recipe is not None else 2
        drop: list[MealItem] = []
        for other in await self._plan.list_in_range(item.household_id, _monday(day) - timedelta(days=2), ctx.end):
            if other.id == item.id:
                continue
            if (other.recipe_id == current and other.meal_type == meal and self._replaceable(other)
                    and day < other.date_day < day + timedelta(days=keeps)
                    and (other.auto_reason or "").startswith(CONTINUE_PREFIX)):
                drop.append(other)
                continue
            ctx.board.cells.add((other.date_day, other.meal_type))
            if other.recipe is not None:
                ctx.board.put(other.date_day, other.meal_type, other.recipe, ctx.scoring.keys.get(other.recipe_id))
        cands = self._candidates(ctx, day, meal)
        # сегодня уже заменили в этом приёме — не возвращаем, пока есть другие варианты
        t0, _ = clock.utc_bounds(today, today)
        rejected = {f.recipe_id for f in await self._plan.feedback_since(item.household_id, t0)
                    if f.action == "replaced" and f.meal_type == meal and f.recipe_id != current}
        fresh = [c for c in cands if c[1].id not in rejected]
        if len(fresh) > 1 or (fresh and fresh[0][1].id != current):
            cands = fresh
        ids = [r.id for _, r, _ in cands]
        if not cands or ids == [current]:
            raise ValidationError("Других подходящих рецептов в ротации нет")
        idx = ids.index(current) if current in ids else -1
        _, recipe, reason = next(c for c in cands[idx + 1:] + cands[:idx + 1] if c[1].id != current)
        if item.origin == "auto":
            self._plan.add_feedback(item, "replaced")      # 🔄 — отзыв о прежнем рецепте
        for other in drop:
            await self._plan.delete(other)
        await self._plan.delete(item)
        await self._plan.flush()
        ctx.end = day + timedelta(days=max(1, recipe.keeps_days or 2) - 1)
        created = await self._cook_at(ctx, day, meal, recipe, reason)
        return created[0].item_id if created else None

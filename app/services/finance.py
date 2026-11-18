"""Финансы семьи: траты, стоимость еды и потерь, бюджет, оценка покупок и блюд.

Все деньги берутся из партий запасов: цена партии / количество = цена единицы.
- «Потрачено» — сумма цен партий, купленных в период: из списка покупок и
  добавленных вручную (без цены — не знаем,
  такие покупки считаются отдельно, чтобы было видно, насколько полна картина).
- «Ушло в еду» — стоимость списаний при готовке и «съел» готового продукта.
- «Выброшено» — стоимость списаний «испортилось», недостач по инвентаризации
  и выброшенных остатков кастрюль.
- Оценки (рецепт, список покупок) — по последней известной цене товара.
"""
from __future__ import annotations


from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core import clock
from app.domain import dec, grams_to_base, quantize
from app.models.stock import StockLot
from app.repositories.household import HouseholdRepository
from app.repositories.plan import PlanRepository
from app.repositories.recipe import CookingLogRepository, RecipeRepository
from app.repositories.stock import StockRepository
from app.schemas.finance import (
    CategorySpend,
    FinanceSummary,
    ItemPrice,
    PotCost,
    RecipeCost,
    WasteItem,
)
from app.services.regular import RegularService
from app.services.shopping import ShoppingService

ZERO = Decimal("0")
MONEY = "0.01"


_d = dec


def unit_price(lot: StockLot) -> Decimal | None:
    if lot.price is None or _d(lot.quantity) <= 0:
        return None
    return _d(lot.price) / _d(lot.quantity)


def money(v: Decimal) -> Decimal:
    return quantize(v, MONEY)


@dataclass
class _Cost:
    value: Decimal = ZERO
    complete: bool = True


class FinanceService:
    def __init__(
        self,
        stock_repo: StockRepository,
        cooking_logs: CookingLogRepository,
        plan: PlanRepository,
        households: HouseholdRepository,
        recipes: RecipeRepository,
        shopping: ShoppingService,
        regular: RegularService,
    ) -> None:
        self._stock_repo = stock_repo
        self._pots = cooking_logs
        self._plan = plan
        self._households = households
        self._recipes = recipes
        self._shopping = shopping
        self._regular = regular

    # ----------------------------------------------------------------- цены
    async def prices(self, household_id: int) -> dict[str, ItemPrice]:
        """Последняя известная цена единицы каждого товара (своя семья)."""
        out: dict[str, ItemPrice] = {}
        for lot in await self._stock_repo.priced_lots(household_id):
            key = lot.product.item_key
            if key in out:
                continue
            up = unit_price(lot)
            if up is not None:
                out[key] = ItemPrice(item_key=key, unit=lot.product.base_unit, unit_price=up, as_of=lot.purchased_on)
        return out

    # -------------------------------------------------------------- кастрюли
    async def _pot_costs(self, pot_ids: list[int]) -> dict[int, _Cost]:
        if not pot_ids:
            return {}
        costs: dict[int, _Cost] = {pid: _Cost() for pid in pot_ids}
        seen: set[int] = set()
        for m in await self._stock_repo.cook_movements(pot_ids):
            seen.add(m.pot_id)
            c = costs[m.pot_id]
            up = unit_price(m.lot) if m.lot is not None else None
            if up is None:
                c.complete = False   # недостача или партия без цены
            else:
                c.value += -_d(m.delta) * up
        for pid in pot_ids:
            if pid not in seen:
                costs[pid].complete = False  # готовили не из учтённых запасов
        return costs

    async def pot_costs(self, household_id: int) -> list[PotCost]:
        pots = await self._pots.of_household(household_id)
        costs = await self._pot_costs([p.id for p in pots])
        out = []
        for p in pots:
            c = costs[p.id]
            total = _d(p.total_cooked_weight)
            out.append(PotCost(
                pot_id=p.id,
                cost=money(c.value) if c.value > 0 else None,
                per_100g=money(c.value * 100 / total) if c.value > 0 and total > 0 else None,
                complete=c.complete,
            ))
        return out

    # --------------------------------------------------------------- рецепты
    async def recipe_costs(self, household_id: int) -> list[RecipeCost]:
        """Оценка стоимости рецепта по последним ценам; доля состава с известной ценой."""
        prices = await self.prices(household_id)
        recipes = await self._recipes.list_full(household_id=household_id, limit=2000)
        out = []
        for r in recipes:
            total, priced_g, all_g = ZERO, ZERO, ZERO
            for ing in r.template_ingredients:
                product = ing.variant.manufacturer.product if ing.variant else None
                g = _d(ing.weight_g)
                all_g += g
                if product is None:
                    continue
                p = prices.get(product.item_key)
                if p is None:
                    continue
                total += grams_to_base(g, product.base_unit, product.piece_weight_g) * p.unit_price
                priced_g += g
            if total <= 0:
                out.append(RecipeCost(recipe_id=r.id, priced_share=ZERO))
                continue
            servings = max(1, r.default_servings or 1)
            cooked = _d(r.estimated_cooked_weight)
            out.append(RecipeCost(
                recipe_id=r.id,
                total=money(total),
                per_portion=money(total / servings),
                per_100g=money(total * 100 / cooked) if cooked > 0 else None,
                priced_share=quantize(priced_g / all_g if all_g else ZERO, "0.01"),
            ))
        return out

    # ---------------------------------------------------------------- сводка
    async def summary(self, household_id: int, start: date, end: date, today: date) -> FinanceSummary:
        t0, t1 = clock.utc_bounds(start, end)   # метки времени в базе — UTC, дни — местные

        # Потрачено: партии, купленные в период
        lots = await self._stock_repo.purchases_between(household_id, start, end)
        spent, unpriced = ZERO, 0
        by_cat: dict[str, Decimal] = {}
        for lot in lots:
            if lot.price is None:
                unpriced += 1
                continue
            spent += _d(lot.price)
            cat = lot.product.category.name if lot.product.category else "Без категории"
            by_cat[cat] = by_cat.get(cat, ZERO) + _d(lot.price)

        # Ушло в еду / выброшено: движения в период по цене их партий
        moves = await self._stock_repo.outgoing_between(household_id, t0, t1)
        eaten, wasted = ZERO, ZERO
        waste: dict[str, WasteItem] = {}
        for m in moves:
            up = unit_price(m.lot) if m.lot is not None else None
            if up is None:
                continue
            value = -_d(m.delta) * up
            if m.reason in ("cook", "eat"):
                eaten += value
            elif m.reason in ("write_off", "inventory"):
                wasted += value
                name = m.lot.product.name
                w = waste.setdefault(name, WasteItem(name=name, value=ZERO, reason="списано"))
                w.value += value

        # Выброшенные остатки кастрюль (приготовлены в период)
        pots = await self._pots.discarded_between(household_id, t0, t1)
        if pots:
            costs = await self._pot_costs([p.id for p in pots])
            eaten_by_pot = await self._plan.eaten_from_pots([p.id for p in pots])
            for p in pots:
                eaten_g = eaten_by_pot.get(p.id, ZERO)
                total = _d(p.total_cooked_weight)
                thrown = max(ZERO, total - eaten_g)
                if total <= 0 or thrown <= 0 or costs[p.id].value <= 0:
                    continue
                value = costs[p.id].value * thrown / total
                # кастрюлю уже посчитали «в еду» при готовке — выброшенную часть переносим
                eaten -= value
                wasted += value
                name = p.recipe.name if p.recipe else "Кастрюля"
                w = waste.setdefault(name, WasteItem(name=name, value=ZERO, reason="выброшен остаток"))
                w.value += value

        # Бюджет и прогноз: что ещё предстоит купить до конца периода по плану
        household = await self._households.get(household_id)
        planned, unknown = ZERO, 0
        if end >= today:
            prices = await self.prices(household_id)
            for it in await self._shopping.to_buy(household_id, max(start, today), end, today):
                if it.to_buy is None:
                    continue
                qty = _d(it.package_amount) * it.package_count if it.package_amount and it.package_count else _d(it.to_buy)
                p = prices.get(it.item_key)
                if p is None:
                    unknown += 1
                else:
                    planned += qty * p.unit_price

        return FinanceSummary(
            start_date=start,
            end_date=end,
            spent=money(spent),
            unpriced_purchases=unpriced,
            by_category=sorted(
                (CategorySpend(name=k, spent=money(v)) for k, v in by_cat.items()),
                key=lambda c: -c.spent,
            ),
            eaten_value=money(max(ZERO, eaten)),
            wasted_value=money(wasted),
            waste=sorted(
                (WasteItem(name=w.name, value=money(w.value), reason=w.reason) for w in waste.values()),
                key=lambda w: -w.value,
            )[:10],
            monthly_budget=household.monthly_budget,
            planned_to_buy=money(planned),
            planned_unknown=unknown,
            snack_spent=money(await self._regular.snack_spent(household_id, start, end)),
            snack_quota=await self._snack_quota(household_id),
        )

    async def _snack_quota(self, household_id: int) -> Decimal | None:
        s = await self._households.planner(household_id)
        return s.snack_quota if s is not None else None

    async def set_budget(self, household_id: int, value: Decimal | None) -> None:
        household = await self._households.get(household_id)
        household.monthly_budget = value
        await self._households.flush()

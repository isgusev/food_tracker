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
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.domain import grams_to_base, quantize
from app.models.household import Household
from app.models.plan import MealPortion
from app.models.product import Product
from app.models.recipe import RecipeCookingLog
from app.models.stock import StockLot, StockMovement
from app.repositories.recipe import RecipeRepository
from app.repositories.stock import StockRepository
from app.schemas.finance import (
    CategorySpend,
    FinanceSummary,
    ItemPrice,
    PotCost,
    RecipeCost,
    WasteItem,
)
from app.services.stock import StockService

ZERO = Decimal("0")
MONEY = "0.01"


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


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
        session: AsyncSession,
        stock_repo: StockRepository,
        recipes: RecipeRepository,
        stock: StockService,
    ) -> None:
        self._s = session
        self._stock_repo = stock_repo
        self._recipes = recipes
        self._stock = stock

    # ----------------------------------------------------------------- цены
    async def prices(self, household_id: int) -> dict[str, ItemPrice]:
        """Последняя известная цена единицы каждого товара (своя семья)."""
        stmt = (
            select(StockLot)
            .where(StockLot.household_id == household_id, StockLot.price.isnot(None))
            .options(joinedload(StockLot.product))
            .order_by(StockLot.purchased_on.desc(), StockLot.id.desc())
        )
        out: dict[str, ItemPrice] = {}
        for lot in (await self._s.execute(stmt)).unique().scalars():
            key = lot.product.search_name
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
        stmt = (
            select(StockMovement)
            .where(StockMovement.pot_id.in_(pot_ids), StockMovement.reason == "cook")
            .options(joinedload(StockMovement.lot))
        )
        costs: dict[int, _Cost] = {pid: _Cost() for pid in pot_ids}
        seen: set[int] = set()
        for m in (await self._s.execute(stmt)).unique().scalars():
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
        pots = list((await self._s.execute(
            select(RecipeCookingLog).where(RecipeCookingLog.household_id == household_id)
        )).scalars())
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
                p = prices.get(product.search_name)
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
        t0, t1 = datetime.combine(start, time.min), datetime.combine(end, time.max)

        # Потрачено: партии, купленные в период
        lots = list((await self._s.execute(
            select(StockLot)
            .where(StockLot.household_id == household_id, StockLot.purchased_on >= start,
                   StockLot.purchased_on <= end, StockLot.source.in_(("purchase", "manual")))
            .options(joinedload(StockLot.product).joinedload(Product.category))
        )).unique().scalars())
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
        moves = list((await self._s.execute(
            select(StockMovement)
            .where(StockMovement.household_id == household_id, StockMovement.created_at >= t0,
                   StockMovement.created_at <= t1, StockMovement.delta < 0)
            .options(joinedload(StockMovement.lot).joinedload(StockLot.product))
        )).unique().scalars())
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
        pots = list((await self._s.execute(
            select(RecipeCookingLog).where(
                RecipeCookingLog.household_id == household_id, RecipeCookingLog.is_discarded.is_(True),
                RecipeCookingLog.cooked_at >= t0, RecipeCookingLog.cooked_at <= t1,
            ).options(joinedload(RecipeCookingLog.recipe))
        )).unique().scalars())
        if pots:
            costs = await self._pot_costs([p.id for p in pots])
            for p in pots:
                eaten_g = sum(
                    (_d(w) for w in (await self._s.execute(
                        select(MealPortion.weight_g).where(
                            MealPortion.eaten_from_pot_id == p.id, MealPortion.is_eaten.is_(True))
                    )).scalars()),
                    ZERO,
                )
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
        household = await self._s.get(Household, household_id)
        planned, unknown = ZERO, 0
        if end >= today:
            prices = await self.prices(household_id)
            for it in await self._stock.to_buy(household_id, max(start, today), end, today):
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
        )

    async def set_budget(self, household_id: int, value: Decimal | None) -> None:
        household = await self._s.get(Household, household_id)
        household.monthly_budget = value
        await self._s.flush()

"""Репозиторий плана питания семьи (блюда и порции)."""
from __future__ import annotations


from datetime import date
from decimal import Decimal

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.domain import MEAL_ORDER
from app.models.plan import MealItem, MealPortion, PlanFeedback, WeekTemplate
from app.models.product import Product, ProductManufacturer, ProductVariant
from app.repositories.base import BaseRepository

ZERO = Decimal("0")

# Приёмы пищи — в порядке дня, а не по алфавиту
MEAL_SORT = case(
    {meal: i for i, meal in enumerate(MEAL_ORDER)},
    value=MealItem.meal_type,
    else_=len(MEAL_ORDER),
)


class PlanRepository(BaseRepository[MealItem]):
    model = MealItem

    def full_query(self):
        return select(MealItem).options(
            selectinload(MealItem.portions).joinedload(MealPortion.member),
            joinedload(MealItem.recipe),
            joinedload(MealItem.cooking_log),
            joinedload(MealItem.variant)
            .joinedload(ProductVariant.manufacturer)
            .joinedload(ProductManufacturer.product)
            .options(joinedload(Product.brand), joinedload(Product.category)),
        )

    async def get_full(self, item_id: int) -> MealItem | None:
        stmt = (
            self.full_query()
            .where(MealItem.id == item_id)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def templates(self, household_id: int) -> list[WeekTemplate]:
        stmt = select(WeekTemplate).where(WeekTemplate.household_id == household_id).order_by(WeekTemplate.name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def template(self, template_id: int) -> WeekTemplate | None:
        return await self._session.get(WeekTemplate, template_id)

    async def get_portion(self, portion_id: int) -> MealPortion | None:
        stmt = select(MealPortion).where(MealPortion.id == portion_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_in_range(
        self, household_id: int, start: date, end: date, *, only_unbought: bool = False
    ) -> list[MealItem]:
        """Блюда семьи за период. only_unbought — только то, что надо купить
        (готовые продукты и рецепты без кастрюли)."""
        stmt = self.full_query().where(
            MealItem.household_id == household_id,
            MealItem.date_day >= start,
            MealItem.date_day <= end,
        )
        if only_unbought:
            stmt = stmt.where(MealItem.cooking_log_id.is_(None))
        stmt = stmt.order_by(MealItem.date_day, MEAL_SORT, MealItem.id)
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def eaten_weights(
        self, household_id: int, since, *, recipe_id: int | None = None, variant_id: int | None = None
    ) -> list[tuple[int, Decimal]]:
        """Съеденные порции членов семьи (без гостей) по рецепту или продукту с даты since (UTC)."""
        stmt = (
            select(MealPortion.member_id, MealPortion.weight_g)
            .join(MealItem, MealPortion.meal_item_id == MealItem.id)
            .where(
                MealItem.household_id == household_id,
                MealPortion.is_eaten.is_(True),
                MealPortion.member_id.isnot(None),
                MealPortion.eaten_at >= since,
            )
        )
        if recipe_id is not None:
            stmt = stmt.where(MealItem.recipe_id == recipe_id)
        else:
            stmt = stmt.where(MealItem.variant_id == variant_id)
        return [(m, Decimal(str(w))) for m, w in (await self._session.execute(stmt)).all()]

    def add_feedback(self, item: MealItem, action: str) -> None:
        """Отзыв о предложении автоплана: по рецепту или по товару готового продукта."""
        product = item.variant.manufacturer.product if item.variant is not None and item.variant.manufacturer else None
        self._session.add(PlanFeedback(
            household_id=item.household_id, recipe_id=item.recipe_id,
            item_key=product.item_key if product is not None and item.recipe_id is None else None,
            meal_type=item.meal_type, action=action,
        ))

    async def feedback_since(self, household_id: int, since) -> list[PlanFeedback]:
        stmt = select(PlanFeedback).where(PlanFeedback.household_id == household_id, PlanFeedback.created_at >= since)
        return list((await self._session.execute(stmt)).scalars().all())

    async def last_recipe_dates(self, household_id: int, before: date) -> dict[int, date]:
        """Последний день, когда рецепт стоял в плане до даты before (для «давно не готовили»)."""
        stmt = (
            select(MealItem.recipe_id, func.max(MealItem.date_day))
            .where(MealItem.household_id == household_id, MealItem.recipe_id.isnot(None),
                   MealItem.date_day < before)
            .group_by(MealItem.recipe_id)
        )
        return {int(r): d for r, d in (await self._session.execute(stmt)).all() if d is not None}

    async def eaten_from_pots(self, pot_ids: list[int]) -> dict[int, Decimal]:
        """Сколько съедено из каждой кастрюли (Σ съеденных порций) — одним запросом."""
        if not pot_ids:
            return {}
        stmt = (
            select(MealPortion.eaten_from_pot_id, func.sum(MealPortion.weight_g))
            .where(MealPortion.eaten_from_pot_id.in_(pot_ids), MealPortion.is_eaten.is_(True))
            .group_by(MealPortion.eaten_from_pot_id)
        )
        return {int(p): Decimal(str(t or 0)) for p, t in (await self._session.execute(stmt)).all()}

    async def reserved_by_pot(self, household_id: int) -> dict[int, Decimal]:
        """Резерв по кастрюлям: Σ несъеденных порций привязанных блюд (один запрос)."""
        stmt = (
            select(MealItem.cooking_log_id, func.sum(MealPortion.weight_g))
            .join(MealPortion, MealPortion.meal_item_id == MealItem.id)
            .where(
                MealItem.household_id == household_id,
                MealItem.cooking_log_id.isnot(None),
                MealPortion.is_eaten.is_(False),
            )
            .group_by(MealItem.cooking_log_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {int(pot): Decimal(str(total or 0)) for pot, total in rows if pot}

    async def unattached_for_recipe(self, household_id: int, recipe_id: int, from_date: date) -> list[MealItem]:
        """Блюда рецепта без кастрюли с даты from_date — в порядке дня (для привязки к свежей кастрюле)."""
        stmt = (
            self.full_query()
            .where(
                MealItem.household_id == household_id,
                MealItem.recipe_id == recipe_id,
                MealItem.cooking_log_id.is_(None),
                MealItem.date_day >= from_date,
            )
            .order_by(MealItem.date_day, MEAL_SORT, MealItem.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def attached_newest_first(self, pot_id: int) -> list[MealItem]:
        """Блюда, привязанные к кастрюле, — с самых поздних (их отвязываем первыми)."""
        stmt = (
            self.full_query()
            .where(MealItem.cooking_log_id == pot_id)
            .order_by(MealItem.date_day.desc(), MEAL_SORT.desc(), MealItem.id.desc())
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def items_touching_pot(self, pot_id: int) -> list[MealItem]:
        """Блюда, привязанные к кастрюле или с порциями, съеденными из неё."""
        eaten_from = exists().where(
            MealPortion.meal_item_id == MealItem.id, MealPortion.eaten_from_pot_id == pot_id
        )
        stmt = (
            self.full_query()
            .where((MealItem.cooking_log_id == pot_id) | eaten_from)
            .order_by(MealItem.date_day, MEAL_SORT, MealItem.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def detach_from_pot(self, pot_id: int, *, keep_eaten_link: bool = True) -> None:
        """Отвязать блюда от кастрюли: несъеденное снова «надо приготовить».

        keep_eaten_link=False — заодно забыть, что съеденное было из неё
        (кастрюля удаляется, а съеденное остаётся в дневнике).
        """
        await self._session.execute(
            update(MealItem)
            .where(MealItem.cooking_log_id == pot_id)
            .values(cooking_log_id=None)
        )
        if not keep_eaten_link:
            await self._session.execute(
                update(MealPortion)
                .where(MealPortion.eaten_from_pot_id == pot_id)
                .values(eaten_from_pot_id=None)
            )

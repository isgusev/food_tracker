"""Репозиторий плана питания семьи (блюда и порции)."""
from __future__ import annotations


from datetime import date
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.domain import MEAL_ORDER
from app.models.plan import MealItem, MealPortion, WeekTemplate
from app.models.product import Product, ProductManufacturer, ProductVariant
from app.repositories.base import BaseRepository

ZERO = Decimal("0")

# Приёмы пищи — в порядке дня, а не по алфавиту
MEAL_SORT = case(
    {meal: i for i, meal in enumerate(MEAL_ORDER)},
    value=MealItem.meal_type,
    else_=len(MEAL_ORDER),
)


def remaining_weight(item: MealItem) -> Decimal:
    """Сколько ещё не съедено по блюду (резерв кастрюли / объём покупки)."""
    return sum(
        (Decimal(str(p.weight_g)) for p in item.portions if not p.is_eaten), Decimal("0")
    )


def fits(planned: Decimal, available: Decimal, tolerance: Decimal) -> bool:
    """Хватает ли: есть не меньше плана за вычетом допуска (доля 0…1)."""
    return planned * (1 - tolerance) <= available


def scale_portions(items: list[MealItem], available: Decimal) -> None:
    """Несъеденные порции блюд — пропорционально под то, что есть в кастрюле.

    Доли членов семьи сохраняются; округляем вниз до грамма, чтобы сумма
    не превысила остаток. Съеденное не трогаем."""
    portions = [p for i in items for p in i.portions if not p.is_eaten]
    total = sum((Decimal(str(p.weight_g)) for p in portions), ZERO)
    if total <= 0 or total <= available:
        return
    k = max(ZERO, available) / total
    for p in portions:
        p.weight_g = (Decimal(str(p.weight_g)) * k).to_integral_value(rounding=ROUND_FLOOR)


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

    async def attach_to_new_pot(
        self,
        household_id: int,
        recipe_id: int,
        pot_id: int,
        from_date: date,
        capacity_g: Decimal,
        tolerance: Decimal = ZERO,
    ) -> int:
        """Свежая кастрюля: привязываем блюда по рецепту с сегодняшнего дня, пока влезают.

        Прошлые неотмеченные планы кастрюлю не «съедают»; на первом
        не поместившемся блюде останавливаемся — более поздние остаются
        «надо приготовить» и попадают в покупки. «Влезает» — с допуском семьи:
        вышло меньше плана не больше чем на tolerance (доля) — блюда привязываются,
        а их несъеденные порции уменьшаются пропорционально выходу.
        """
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
        items = list((await self._session.execute(stmt)).unique().scalars().all())
        reserved = ZERO
        attached: list[MealItem] = []
        for item in items:
            need = remaining_weight(item)
            if need <= 0:
                continue  # всё уже съедено
            if not fits(reserved + need, capacity_g, tolerance):
                break
            reserved += need
            item.cooking_log_id = pot_id
            attached.append(item)
        if reserved > capacity_g:
            scale_portions(attached, capacity_g)
        await self._session.flush()
        return len(attached)

    async def release_overbooked(
        self, pot_id: int, available_g: Decimal, tolerance: Decimal = ZERO
    ) -> int:
        """Кастрюля убыла — с конца отвязываем блюда, которым уже не хватает.

        С допуском (tolerance > 0, события самой кастрюли: готовка, «съел больше»,
        правка остатка) небольшая нехватка не отвязывает, а пропорционально
        уменьшает несъеденные порции оставшихся блюд.
        """
        stmt = (
            self.full_query()
            .where(MealItem.cooking_log_id == pot_id)
            .order_by(MealItem.date_day.desc(), MEAL_SORT.desc(), MealItem.id.desc())
        )
        items = list((await self._session.execute(stmt)).unique().scalars().all())
        reserved = sum((remaining_weight(i) for i in items), ZERO)
        released = 0
        kept: list[MealItem] = []
        for item in items:
            need = remaining_weight(item)
            if need > 0 and not fits(reserved, available_g, tolerance):
                reserved -= need
                item.cooking_log_id = None
                released += 1
            else:
                kept.append(item)
        if tolerance > 0 and reserved > available_g:
            scale_portions(kept, available_g)
        await self._session.flush()
        return released

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

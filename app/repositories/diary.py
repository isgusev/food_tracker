"""Репозиторий дневника питания."""
from __future__ import annotations


from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload

from app.domain import (
    MEAL_ORDER,
    STATUS_COOKED_PLAN,
    STATUS_TEMPLATE_PLAN,
    pot_share,
)
from app.models.diary import DiaryLog
from app.models.product import Product, ProductManufacturer, ProductVariant
from app.models.recipe import Recipe, RecipeCookingLog
from app.repositories.base import BaseRepository


# Сортировка приёмов пищи как в течение дня (а не по алфавиту названий)
MEAL_SORT = case(
    {meal: i for i, meal in enumerate(MEAL_ORDER)},
    value=DiaryLog.meal_type,
    else_=len(MEAL_ORDER),
)


class DiaryRepository(BaseRepository[DiaryLog]):
    model = DiaryLog

    def full_query(self):
        # одним JOIN'ом тянем рецепт (с категорией), кастрюлю и её ингредиенты — лечит N+1
        return (
            select(DiaryLog)
            .options(
                joinedload(DiaryLog.recipe).joinedload(Recipe.recipe_category),
                joinedload(DiaryLog.cooking_log).joinedload(
                    RecipeCookingLog.actual_ingredients
                ),
                # готовый продукт: версия → производитель → продукт (+бренд, категория)
                joinedload(DiaryLog.variant)
                .joinedload(ProductVariant.manufacturer)
                .joinedload(ProductManufacturer.product)
                .options(joinedload(Product.brand), joinedload(Product.category)),
            )
        )

    async def get_full(self, log_id: int) -> DiaryLog | None:
        stmt = self.full_query().where(DiaryLog.id == log_id)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def get_variant_full(self, variant_id: int) -> ProductVariant | None:
        """Версия продукта с деревом каталога (для названия и КБЖУ готового продукта)."""
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.id == variant_id)
            .options(
                joinedload(ProductVariant.manufacturer)
                .joinedload(ProductManufacturer.product)
                .options(joinedload(Product.brand), joinedload(Product.category))
            )
        )
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def list_for_day(self, user_id: int, date_day: date) -> list[DiaryLog]:
        stmt = (
            self.full_query()
            .where(DiaryLog.user_id == user_id, DiaryLog.date_day == date_day)
            .order_by(MEAL_SORT, DiaryLog.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def list_in_range(
        self, user_id: int, start_date: date, end_date: date
    ) -> list[DiaryLog]:
        """Все записи (планы и факты) за диапазон дат — для недельного планировщика."""
        stmt = (
            self.full_query()
            .where(
                DiaryLog.user_id == user_id,
                DiaryLog.date_day >= start_date,
                DiaryLog.date_day <= end_date,
            )
            .order_by(DiaryLog.date_day, MEAL_SORT, DiaryLog.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def planned_weight_by_pot(self, user_id: int) -> dict[int, Decimal]:
        """Резерв планов по каждой кастрюле пользователя: Σ порция × едоки (один запрос)."""
        share = DiaryLog.weight_g * func.coalesce(DiaryLog.servings_multiplier, 1)
        stmt = (
            select(DiaryLog.cooking_log_id, func.sum(share))
            .where(
                DiaryLog.user_id == user_id,
                DiaryLog.cooking_log_id.isnot(None),
                DiaryLog.status.in_([STATUS_TEMPLATE_PLAN, STATUS_COOKED_PLAN]),
            )
            .group_by(DiaryLog.cooking_log_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {int(pot_id): Decimal(str(total or 0)) for pot_id, total in rows if pot_id}

    async def list_planned_in_range(
        self, user_id: int, start_date: date, end_date: date
    ) -> list[DiaryLog]:
        stmt = (
            self.full_query()
            .where(
                DiaryLog.user_id == user_id,
                DiaryLog.date_day >= start_date,
                DiaryLog.date_day <= end_date,
                DiaryLog.status == STATUS_TEMPLATE_PLAN,
            )
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def reattach_template_plans(
        self,
        user_id: int,
        recipe_id: int,
        cooking_log_id: int,
        from_date: date,
        capacity_g: Decimal,
    ) -> int:
        """При готовке привязываем планы по рецепту к свежей кастрюле — сколько влезет.

        Берём только планы начиная с дня готовки (прошлые неотмеченные планы не
        должны «съедать» кастрюлю) в хронологическом порядке и останавливаемся
        на первом, который уже не помещается: следующие по времени блюда
        остаются «надо приготовить» и попадают в список покупок.
        """
        stmt = (
            select(DiaryLog)
            .where(
                DiaryLog.user_id == user_id,
                DiaryLog.recipe_id == recipe_id,
                DiaryLog.status == STATUS_TEMPLATE_PLAN,
                DiaryLog.date_day >= from_date,
            )
            .order_by(DiaryLog.date_day, MEAL_SORT, DiaryLog.id)
        )
        plans = list((await self._session.execute(stmt)).scalars().all())
        reserved = Decimal("0")
        attached = 0
        for plan in plans:
            share = pot_share(plan.weight_g, plan.servings_multiplier)
            if reserved + share > capacity_g:
                break
            reserved += share
            plan.cooking_log_id = cooking_log_id
            plan.status = STATUS_COOKED_PLAN
            attached += 1
        await self._session.flush()
        return attached

    async def release_overbooked(self, cooking_log_id: int, available_g: Decimal) -> int:
        """Кастрюлю доели/подправили остаток — планы, которым уже не хватает, отвязываем.

        Освобождаем с конца (самые поздние планы), пока резерв не уложится в
        остаток. Отвязанные планы снова «надо приготовить» и попадают в покупки.
        """
        stmt = (
            select(DiaryLog)
            .where(
                DiaryLog.cooking_log_id == cooking_log_id,
                DiaryLog.status == STATUS_COOKED_PLAN,
            )
            .order_by(DiaryLog.date_day.desc(), MEAL_SORT.desc(), DiaryLog.id.desc())
        )
        plans = list((await self._session.execute(stmt)).scalars().all())
        reserved = sum(
            (pot_share(p.weight_g, p.servings_multiplier) for p in plans), Decimal("0")
        )
        released = 0
        for plan in plans:
            if reserved <= available_g:
                break
            reserved -= pot_share(plan.weight_g, plan.servings_multiplier)
            plan.cooking_log_id = None
            plan.status = STATUS_TEMPLATE_PLAN
            released += 1
        await self._session.flush()
        return released

    async def detach_plans_from_pot(self, cooking_log_id: int) -> int:
        """При удалении кастрюли откатываем cooked_plan обратно в template_plan."""
        from sqlalchemy import update

        stmt = (
            update(DiaryLog)
            .where(
                DiaryLog.cooking_log_id == cooking_log_id,
                DiaryLog.status == STATUS_COOKED_PLAN,
            )
            .values(status=STATUS_TEMPLATE_PLAN, cooking_log_id=None)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

    async def logs_using_pot(self, cooking_log_id: int) -> list[DiaryLog]:
        """Все записи дневника (планы и факты), ссылающиеся на кастрюлю."""
        stmt = (
            self.full_query()
            .where(DiaryLog.cooking_log_id == cooking_log_id)
            .order_by(DiaryLog.date_day, MEAL_SORT, DiaryLog.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def unattach_pot_keep_recipe(self, cooking_log_id: int) -> int:
        """Отвязка записей дневника от удаляемой кастрюли, сохраняя recipe_id.

        Планы остаются «надо приготовить» (template_plan, привязка к шаблону →
        попадают в план покупок); факты («съедено») сохраняются как приём пищи
        без холодильника — обязательность учёта в нём снимается.
        """
        from sqlalchemy import update

        stmt = (
            update(DiaryLog)
            .where(DiaryLog.cooking_log_id == cooking_log_id)
            .values(cooking_log_id=None)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

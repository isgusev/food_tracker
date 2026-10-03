"""Репозиторий дневника питания."""
from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.domain import STATUS_COOKED_PLAN, STATUS_TEMPLATE_PLAN
from app.models.diary import DiaryLog
from app.models.recipe import Recipe, RecipeCookingLog
from app.repositories.base import BaseRepository


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
            )
        )

    async def get_full(self, log_id: int) -> DiaryLog | None:
        stmt = self.full_query().where(DiaryLog.id == log_id)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def list_for_day(self, user_id: int, date_day: str) -> list[DiaryLog]:
        stmt = (
            self.full_query()
            .where(DiaryLog.user_id == user_id, DiaryLog.date_day == date_day)
            .order_by(DiaryLog.meal_type, DiaryLog.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def list_planned_in_range(
        self, user_id: int, start_date: str, end_date: str
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
        self, user_id: int, recipe_id: int, cooking_log_id: int
    ) -> int:
        """При готовке инстанса привязываем будущие template_plan → cooked_plan."""
        from sqlalchemy import update

        stmt = (
            update(DiaryLog)
            .where(
                DiaryLog.user_id == user_id,
                DiaryLog.recipe_id == recipe_id,
                DiaryLog.status == STATUS_TEMPLATE_PLAN,
            )
            .values(cooking_log_id=cooking_log_id, status=STATUS_COOKED_PLAN)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

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
            .order_by(DiaryLog.date_day)
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

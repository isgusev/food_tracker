"""Репозитории семьи и её членов."""
from __future__ import annotations


from sqlalchemy import delete, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.models.household import Household, HouseholdMember
from app.models.plan import MealItem
from app.models.recipe import Recipe, RecipeCookingLog
from app.repositories.base import BaseRepository


class HouseholdRepository(BaseRepository[Household]):
    model = Household

    async def get_with_members(self, household_id: int) -> Household | None:
        stmt = (
            select(Household)
            .where(Household.id == household_id)
            .options(selectinload(Household.members).joinedload(HouseholdMember.user))
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_invite_code(self, code: str) -> Household | None:
        stmt = select(Household).where(Household.invite_code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def move_all_data(self, from_id: int, to_id: int) -> None:
        """Переносит рецепты, холодильник, план и членов одной семьи в другую."""
        for model in (Recipe, RecipeCookingLog, MealItem, HouseholdMember):
            await self._session.execute(
                update(model)
                .where(model.household_id == from_id)
                .values(household_id=to_id)
            )


    async def delete_by_id(self, household_id: int) -> None:
        """Удаление SQL-ом: ORM-удаление обнулило бы household_id у уже
        перенесённых членов семьи из загруженной коллекции members."""
        await self._session.execute(delete(Household).where(Household.id == household_id))


class MemberRepository(BaseRepository[HouseholdMember]):
    model = HouseholdMember

    async def get_by_user(self, user_id: int) -> HouseholdMember | None:
        stmt = (
            select(HouseholdMember)
            .where(HouseholdMember.user_id == user_id)
            .options(joinedload(HouseholdMember.household))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

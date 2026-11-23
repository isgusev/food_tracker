"""Репозитории семьи и её членов."""
from __future__ import annotations


from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import aliased, joinedload, selectinload

from app.models.household import Household, HouseholdMember, PlannerSettings
from app.models.plan import MealItem, PlanFeedback, WeekTemplate
from app.models.receipt import Receipt, ReceiptAlias
from app.models.recipe import Recipe, RecipeCookingLog
from app.models.stock import HouseholdProduct, ShoppingList, StockLot, StockMark, StockMovement
from app.models.user import RegistrationInvite
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
        """Переносит ВСЁ семьи from_id в семью to_id: рецепты, кастрюли, план, членов семьи, запасы
        (партии, движения, пачки), списки покупок, настройки товаров, шаблоны недель, отзывы автоплана, чеки и их
        выученные сопоставления, приглашения. Старая семья потом удаляется — и всё, что осталось
        за ней, каскадом пропадает, поэтому список здесь должен быть полным.

        Что нарушило бы уникальность в новой семье, решается в её пользу: настройки того же товара,
        та же пачка «Честного знака», тот же чек, то же сопоставление чека — остаются её; второй
        активный список покупок переносится закрытым. Настройки планировщика — её."""
        hp = HouseholdProduct
        await self._session.execute(delete(hp).where(
            hp.household_id == from_id,
            hp.item_key.in_(select(hp.item_key).where(hp.household_id == to_id)),
        ))
        mark2 = aliased(StockMark)
        await self._session.execute(delete(StockMark).where(
            StockMark.household_id == from_id,
            exists().where(mark2.household_id == to_id, mark2.gtin == StockMark.gtin, mark2.serial == StockMark.serial),
        ))
        rc2 = aliased(Receipt)
        await self._session.execute(delete(Receipt).where(
            Receipt.household_id == from_id,
            exists().where(rc2.household_id == to_id, rc2.qr_raw == Receipt.qr_raw),
        ))
        al2 = aliased(ReceiptAlias)
        await self._session.execute(delete(ReceiptAlias).where(
            ReceiptAlias.household_id == from_id,
            exists().where(
                al2.household_id == to_id, al2.norm_name == ReceiptAlias.norm_name,
                al2.store_inn.is_not_distinct_from(ReceiptAlias.store_inn),
            ),
        ))
        target_active = await self._session.scalar(select(ShoppingList.id).where(
            ShoppingList.household_id == to_id, ShoppingList.status == "active"))
        if target_active is not None:
            await self._session.execute(
                update(ShoppingList)
                .where(ShoppingList.household_id == from_id, ShoppingList.status == "active")
                .values(status="closed", closed_at=func.now())
            )
        await self._session.execute(delete(PlannerSettings).where(PlannerSettings.household_id == from_id))
        for model in (
            Recipe, RecipeCookingLog, MealItem, WeekTemplate, PlanFeedback, HouseholdMember,
            StockLot, StockMovement, StockMark, ShoppingList, HouseholdProduct,
            Receipt, ReceiptAlias, RegistrationInvite,
        ):
            await self._session.execute(
                update(model).where(model.household_id == from_id).values(household_id=to_id)
            )

    async def planner(self, household_id: int) -> PlannerSettings | None:
        return await self._session.get(PlannerSettings, household_id)

    async def planner_or_create(self, household_id: int) -> PlannerSettings:
        s = await self.planner(household_id)
        if s is None:
            s = PlannerSettings(household_id=household_id, max_special_per_week=1)
            self._session.add(s)
            await self._session.flush()
        return s

    async def delete_by_id(self, household_id: int) -> None:
        """Удаление SQL-ом: ORM-удаление обнулило бы household_id у уже
        перенесённых членов семьи из загруженной коллекции members."""
        await self._session.execute(delete(PlannerSettings).where(PlannerSettings.household_id == household_id))
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

    async def active_in(self, household_id: int) -> list[HouseholdMember]:
        stmt = (
            select(HouseholdMember)
            .where(HouseholdMember.household_id == household_id, HouseholdMember.is_active.is_(True))
            .order_by(HouseholdMember.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

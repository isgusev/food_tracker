"""Сервис семьи: создание при первом входе, члены семьи, цели КБЖУ, приглашения."""
from __future__ import annotations


import secrets

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.household import Household, HouseholdMember
from app.models.user import User
from app.repositories.household import HouseholdRepository, MemberRepository
from app.schemas.household import (
    HouseholdResponse,
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    Targets,
)

# Без похожих символов (0/O, 1/I/L), чтобы код легко продиктовать
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_invite_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def _targets(member: HouseholdMember) -> Targets:
    return Targets(
        calories=member.target_calories,
        proteins=member.target_proteins,
        fats=member.target_fats,
        carbs=member.target_carbs,
    )


def _apply_targets(member: HouseholdMember, t: Targets) -> None:
    member.target_calories = t.calories
    member.target_proteins = t.proteins
    member.target_fats = t.fats
    member.target_carbs = t.carbs


class HouseholdService:
    def __init__(self, households: HouseholdRepository, members: MemberRepository) -> None:
        self._households = households
        self._members = members

    async def ensure_member(self, user: User) -> HouseholdMember:
        """Член семьи текущего пользователя; при первом входе создаёт ему семью."""
        member = await self._members.get_by_user(user.id)
        if member is not None:
            return member
        household = Household(name=f"Семья {user.username}", invite_code=await self._unique_code())
        self._households.add(household)
        await self._households.flush()
        member = HouseholdMember(household_id=household.id, user_id=user.id, name=user.username)
        self._members.add(member)
        await self._members.flush()
        return member

    async def _unique_code(self) -> str:
        while True:
            code = new_invite_code()
            if await self._households.get_by_invite_code(code) is None:
                return code

    async def get(self, me: HouseholdMember) -> HouseholdResponse:
        household = await self._households.get_with_members(me.household_id)
        assert household is not None
        return HouseholdResponse(
            id=household.id,
            name=household.name,
            invite_code=household.invite_code,
            monthly_budget=household.monthly_budget,
            me_member_id=me.id,
            members=[self.member_response(m, me) for m in household.members],
        )

    @staticmethod
    def member_response(m: HouseholdMember, me: HouseholdMember) -> MemberResponse:
        return MemberResponse(
            id=m.id,
            name=m.name,
            user_id=m.user_id,
            username=m.user.username if m.user_id and m.user else None,
            is_active=m.is_active,
            is_me=m.id == me.id,
            targets=_targets(m),
        )

    async def rename(self, me: HouseholdMember, name: str) -> HouseholdResponse:
        household = await self._households.get(me.household_id)
        household.name = name
        await self._households.flush()
        return await self.get(me)

    async def regenerate_code(self, me: HouseholdMember) -> HouseholdResponse:
        household = await self._households.get(me.household_id)
        household.invite_code = await self._unique_code()
        await self._households.flush()
        return await self.get(me)

    # --- ЧЛЕНЫ СЕМЬИ ---
    async def get_member(self, household_id: int, member_id: int) -> HouseholdMember:
        member = await self._members.get(member_id)
        if member is None or member.household_id != household_id:
            raise NotFoundError("Член семьи не найден")
        return member

    async def add_member(self, me: HouseholdMember, data: MemberCreate) -> HouseholdResponse:
        member = HouseholdMember(household_id=me.household_id, name=data.name)
        _apply_targets(member, data.targets)
        self._members.add(member)
        await self._members.flush()
        return await self.get(me)

    async def update_member(
        self, me: HouseholdMember, member_id: int, data: MemberUpdate
    ) -> HouseholdResponse:
        member = await self.get_member(me.household_id, member_id)
        fields = data.model_dump(exclude_unset=True)
        if "name" in fields and data.name is not None:
            member.name = data.name
        if "targets" in fields and data.targets is not None:
            _apply_targets(member, data.targets)
        if "is_active" in fields and data.is_active is not None:
            if member.user_id is not None and not data.is_active:
                raise ValidationError("Участника со своим аккаунтом нельзя скрыть из семьи")
            member.is_active = data.is_active
        await self._members.flush()
        return await self.get(me)

    # --- ПРИГЛАШЕНИЕ ---
    async def join(self, me: HouseholdMember, code: str) -> HouseholdResponse:
        """Вступить в семью по коду. Всё, что было у вас (рецепты, холодильник,
        план, члены семьи без аккаунта), переезжает в новую семью."""
        target = await self._households.get_by_invite_code(code)
        if target is None:
            raise NotFoundError("Семья с таким кодом не найдена")
        if target.id == me.household_id:
            raise ValidationError("Вы уже в этой семье")
        source = await self._households.get_with_members(me.household_id)
        others_with_accounts = [m for m in source.members if m.user_id and m.id != me.id]
        if others_with_accounts:
            raise ConflictError(
                "В вашей семье есть другие участники с аккаунтами — "
                "вступить в другую семью можно только из семьи, где вы один"
            )
        await self._households.move_all_data(source.id, target.id)
        await self._households.delete_by_id(source.id)
        me = await self._members.get_by_user(me.user_id)
        return await self.get(me)

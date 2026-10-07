"""Эндпоинты семьи: состав, цели КБЖУ, приглашение по коду."""
from __future__ import annotations


from fastapi import APIRouter

from app.api.deps import CurrentMemberDep, HouseholdServiceDep
from app.schemas.household import (
    HouseholdResponse,
    HouseholdUpdate,
    JoinRequest,
    MemberCreate,
    MemberUpdate,
)

router = APIRouter(prefix="/household", tags=["Семья"])


@router.get("", response_model=HouseholdResponse)
async def get_household(me: CurrentMemberDep, service: HouseholdServiceDep):
    """Моя семья: участники, их цели КБЖУ, код приглашения."""
    return await service.get(me)


@router.patch("", response_model=HouseholdResponse)
async def rename_household(payload: HouseholdUpdate, me: CurrentMemberDep, service: HouseholdServiceDep):
    return await service.rename(me, payload.name)


@router.post("/members", response_model=HouseholdResponse, status_code=201)
async def add_member(payload: MemberCreate, me: CurrentMemberDep, service: HouseholdServiceDep):
    """Добавить члена семьи без аккаунта (ребёнок и т. п.)."""
    return await service.add_member(me, payload)


@router.patch("/members/{member_id}", response_model=HouseholdResponse)
async def update_member(
    member_id: int, payload: MemberUpdate, me: CurrentMemberDep, service: HouseholdServiceDep
):
    """Имя, цели КБЖУ; is_active=false — скрыть из планирования (история остаётся)."""
    return await service.update_member(me, member_id, payload)


@router.post("/invite-code", response_model=HouseholdResponse)
async def regenerate_invite_code(me: CurrentMemberDep, service: HouseholdServiceDep):
    """Выпустить новый код приглашения (старый перестаёт работать)."""
    return await service.regenerate_code(me)


@router.post("/join", response_model=HouseholdResponse)
async def join_household(payload: JoinRequest, me: CurrentMemberDep, service: HouseholdServiceDep):
    """Вступить в семью по коду; ваши рецепты, холодильник и план переезжают туда."""
    return await service.join(me, payload.invite_code)

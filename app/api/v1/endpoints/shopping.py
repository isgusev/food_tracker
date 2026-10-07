"""Эндпоинт «Список покупок» семьи на период."""
from __future__ import annotations


from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import CurrentMemberDep, PlanServiceDep
from app.schemas.plan import ShoppingListResponse

router = APIRouter(prefix="/shopping-list", tags=["Список покупок"])


@router.get("", response_model=ShoppingListResponse)
async def get_shopping_list(
    service: PlanServiceDep,
    me: CurrentMemberDep,
    start_date: date = Query(),
    end_date: date = Query(),
):
    """Что купить под план семьи: несъеденные порции блюд, которых нет в холодильнике."""
    items = await service.shopping_list(me.household_id, start_date, end_date)
    return ShoppingListResponse(start_date=start_date, end_date=end_date, items=items)

"""Эндпоинт «Список покупок» по диапазону дат.

Вынесен из diary.py в отдельный префикс /shopping-list, чтобы не терять
обратную совместимость со старыми клиентами (UI обращался к
/diary/{user_id}/shopping-list). user_id всегда берётся из JWT.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DiaryServiceDep
from app.core.exceptions import ValidationError
from app.schemas.diary import ShoppingListResponse

router = APIRouter(prefix="/shopping-list", tags=["Список покупок"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("", response_model=ShoppingListResponse)
async def get_shopping_list(
    service: DiaryServiceDep,
    current_user: CurrentUserDep,
    start_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Агрегированный список покупок по планам текущего пользователя."""
    if start_date > end_date:
        raise ValidationError("Дата окончания не может быть раньше даты начала")
    items = await service.shopping_list(current_user.id, start_date, end_date)
    return ShoppingListResponse(
        start_date=start_date, end_date=end_date, items=items
    )


# Совместимость: старый путь с user_id в URL — id из пути игнорируется,
# данные всегда отдаются только для пользователя из токена.
@router.get("/{path_user_id}", response_model=ShoppingListResponse)
async def get_shopping_list_legacy(
    path_user_id: int,
    service: DiaryServiceDep,
    current_user: CurrentUserDep,
    start_date: str = Query(pattern=_DATE_RE.pattern),
    end_date: str = Query(pattern=_DATE_RE.pattern),
):
    return await get_shopping_list(service, current_user, start_date, end_date)

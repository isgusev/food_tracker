"""Эндпоинты дневника питания: планы, факты, список покупок.

user_id всегда берётся из JWT (CurrentUserDep) — клиент не может
читать/писать чужие записи.
"""
from __future__ import annotations


from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DiaryServiceDep
from app.schemas.diary import (
    DiaryLogCreate,
    DiaryLogResponse,
    DiaryLogUpdateWeight,
    ShoppingListResponse,
)

router = APIRouter(prefix="/diary", tags=["Дневник питания"])


@router.get("/day/{date_day}", response_model=list[DiaryLogResponse])
async def get_day_logs(
    date_day: str, service: DiaryServiceDep, current_user: CurrentUserDep
):
    """Записи дневника текущего пользователя на указанную дату (YYYY-MM-DD)."""
    return await service.list_for_day(current_user.id, date_day)


@router.post("/", response_model=DiaryLogResponse, status_code=201)
async def add_plan(
    plan_in: DiaryLogCreate, service: DiaryServiceDep, current_user: CurrentUserDep
):
    """Добавить план блюда в дневник."""
    return await service.add_plan(current_user.id, plan_in)


@router.patch("/{log_id}/weight", response_model=DiaryLogResponse)
async def update_weight(
    log_id: int,
    payload: DiaryLogUpdateWeight,
    service: DiaryServiceDep,
    current_user: CurrentUserDep,
):
    """Изменить вес порции (план или факт) без смены статуса."""
    log = await service.get_owned(log_id, current_user.id)
    return await service.update_weight(log, payload.weight_g)


@router.post("/{log_id}/eat", response_model=DiaryLogResponse)
async def mark_eaten(
    log_id: int,
    payload: DiaryLogUpdateWeight,
    service: DiaryServiceDep,
    current_user: CurrentUserDep,
):
    """Отметить «съедено»: план → факт, списание веса из кастрюли."""
    log = await service.get_owned(log_id, current_user.id)
    return await service.mark_eaten(log, payload.weight_g)


@router.delete("/{log_id}", status_code=204)
async def delete_log(
    log_id: int, service: DiaryServiceDep, current_user: CurrentUserDep
):
    """Удалить запись дневника (факт возвращает вес в кастрюлю)."""
    log = await service.get_owned(log_id, current_user.id)
    await service.delete(log)


@router.get("/pot-status/{recipe_id}", response_model=PotSourceStatus)
async def get_pot_status(
    recipe_id: int,
    service: DiaryServiceDep,
    current_user: CurrentUserDep,
    portion_g: Decimal | None = Query(default=None, gt=0, le=Decimal("999.9")),
):
    """Есть ли активная кастрюля по рецепту и сколько в ней свободно (для формы планирования)."""
    return await service.pot_status_for_recipe(current_user.id, recipe_id, portion_g)


@router.get("/shopping-list", response_model=ShoppingListResponse)
async def get_shopping_list(
    service: DiaryServiceDep,
    current_user: CurrentUserDep,
    start_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """Агрегированный список покупок по планам на диапазон дат."""
    items = await service.shopping_list(current_user.id, start_date, end_date)
    return ShoppingListResponse(
        start_date=start_date, end_date=end_date, items=items
    )

"""Эндпоинты дневника питания и списка покупок."""

from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import DiaryServiceDep
from app.schemas.diary import (
    DiaryLogCreate,
    DiaryLogResponse,
    DiaryLogUpdateWeight,
    ShoppingListResponse,
)

router = APIRouter(prefix="/diary", tags=["Дневник питания"])


@router.get("/shopping-list", response_model=ShoppingListResponse)
async def shopping_list(
    service: DiaryServiceDep,
    user_id: str = Query(min_length=1),
    start_date: date = Query(),
    end_date: date = Query(),
):
    items = await service.shopping_list(user_id, start_date.isoformat(), end_date.isoformat())
    return ShoppingListResponse(start_date=start_date, end_date=end_date, items=items)


@router.get("/{user_id}/{date_day}", response_model=list[DiaryLogResponse])
async def get_diary_for_day(user_id: str, date_day: str, service: DiaryServiceDep):
    return await service.list_for_day(user_id, date_day)


@router.post("/", response_model=DiaryLogResponse, status_code=201)
async def add_plan(plan_in: DiaryLogCreate, service: DiaryServiceDep):
    log = await service.add_plan(plan_in)
    day_logs = await service.list_for_day(log.user_id, log.date_day)
    return next(entry for entry in day_logs if entry.id == log.id)


@router.patch("/{log_id}/weight", response_model=DiaryLogResponse)
async def change_planned_weight(
    log_id: int, weight_update: DiaryLogUpdateWeight, service: DiaryServiceDep
):
    log = await service.update_weight(log_id, weight_update.weight_g)
    day_logs = await service.list_for_day(log.user_id, log.date_day)
    return next(entry for entry in day_logs if entry.id == log.id)


@router.patch("/{log_id}/eat", response_model=DiaryLogResponse)
async def commit_or_change_fact(
    log_id: int, weight_update: DiaryLogUpdateWeight, service: DiaryServiceDep
):
    """Превращаем план в факт или меняем вес порции съеденного."""
    log = await service.mark_eaten(log_id, weight_update.weight_g)
    day_logs = await service.list_for_day(log.user_id, log.date_day)
    return next(entry for entry in day_logs if entry.id == log.id)


@router.delete("/{log_id}", status_code=204)
async def delete_diary_log(log_id: int, service: DiaryServiceDep):
    await service.delete(log_id)

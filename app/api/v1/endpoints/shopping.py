"""Покупки семьи: расчёт «что купить» и общий список с отметками «куплено»."""
from __future__ import annotations


import datetime as dt

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentMemberDep, CurrentUserDep, StockServiceDep
from app.schemas.stock import (
    ExtraLine,
    LineCheck,
    LineUpdate,
    ListGenerate,
    ShoppingListOut,
    ShoppingPreview,
)

router = APIRouter(tags=["Список покупок"])


@router.get("/shopping-list", response_model=ShoppingPreview)
async def preview(
    service: StockServiceDep,
    me: CurrentMemberDep,
    start_date: dt.date = Query(),
    end_date: dt.date = Query(),
):
    """Что купить на период: потребность плана минус свободные запасы (без сохранения)."""
    items = await service.to_buy(me.household_id, start_date, end_date, dt.date.today())
    return ShoppingPreview(start_date=start_date, end_date=end_date, items=items)


@router.get("/shopping-lists/active", response_model=ShoppingListOut | None)
async def active_list(service: StockServiceDep, me: CurrentMemberDep):
    """Активный общий список семьи (null — списка нет)."""
    return await service.active_list(me.household_id)


@router.post("/shopping-lists", response_model=ShoppingListOut)
async def generate(payload: ListGenerate, service: StockServiceDep, me: CurrentMemberDep):
    """Сформировать или обновить активный список: отмеченное и добавленное вручную остаётся."""
    return await service.generate(me.household_id, payload.start_date, payload.end_date, dt.date.today())


@router.post("/shopping-lists/{list_id}/close", status_code=204)
async def close(list_id: int, service: StockServiceDep, me: CurrentMemberDep):
    await service.close(await service.get_owned_list(list_id, me.household_id))


@router.post("/shopping-lists/{list_id}/lines", response_model=ShoppingListOut, status_code=201)
async def add_extra(list_id: int, payload: ExtraLine, service: StockServiceDep, me: CurrentMemberDep):
    """Внеплановая покупка."""
    lst = await service.get_owned_list(list_id, me.household_id)
    return await service.add_extra(lst, payload.product_id, payload.quantity)


@router.post("/shopping-lists/lines/{line_id}/check", response_model=ShoppingListOut)
async def check(
    line_id: int, payload: LineCheck, service: StockServiceDep, me: CurrentMemberDep, user: CurrentUserDep
):
    """«Куплено» — товар сразу попадает в запасы (количество по умолчанию — предложенные упаковки)."""
    lst, line = await service.get_owned_line(line_id, me.household_id)
    return await service.check(lst, line, payload, user.id, dt.date.today())


@router.post("/shopping-lists/lines/{line_id}/uncheck", response_model=ShoppingListOut)
async def uncheck(line_id: int, service: StockServiceDep, me: CurrentMemberDep):
    lst, line = await service.get_owned_line(line_id, me.household_id)
    return await service.uncheck(lst, line)


@router.patch("/shopping-lists/lines/{line_id}", response_model=ShoppingListOut)
async def update_line(line_id: int, payload: LineUpdate, service: StockServiceDep, me: CurrentMemberDep):
    """Количество, цена, бренд, срок годности (для купленного — правится партия в запасах)."""
    lst, line = await service.get_owned_line(line_id, me.household_id)
    return await service.update_line(lst, line, payload)


@router.delete("/shopping-lists/lines/{line_id}", response_model=ShoppingListOut)
async def delete_line(line_id: int, service: StockServiceDep, me: CurrentMemberDep):
    lst, line = await service.get_owned_line(line_id, me.household_id)
    return await service.delete_line(lst, line)

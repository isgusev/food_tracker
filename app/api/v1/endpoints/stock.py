"""Запасы семьи: остатки по товарам, ручное добавление, списание, инвентаризация."""
from __future__ import annotations


import datetime as dt

from fastapi import APIRouter

from app.api.deps import CurrentMemberDep, CurrentUserDep, StockServiceDep
from app.schemas.stock import Inventory, ItemFlags, LotAdd, MovementResponse, StockItem, WriteOff

router = APIRouter(prefix="/stock", tags=["Запасы"])


@router.get("", response_model=list[StockItem])
async def summary(service: StockServiceDep, me: CurrentMemberDep):
    """Что есть дома: по товарам (все бренды вместе), с партиями и сроками."""
    return await service.summary(me.household_id, dt.date.today())


@router.post("/lots", response_model=list[StockItem], status_code=201)
async def add_lot(payload: LotAdd, service: StockServiceDep, me: CurrentMemberDep, user: CurrentUserDep):
    """Добавить в запасы мимо списка покупок."""
    await service.add_lot(me.household_id, user.id, payload, source="manual", today=dt.date.today())
    return await service.summary(me.household_id, dt.date.today())


@router.post("/items/{product_id}/write-off", response_model=list[StockItem])
async def write_off(
    product_id: int, payload: WriteOff, service: StockServiceDep, me: CurrentMemberDep, user: CurrentUserDep
):
    """Испортилось / выбросили (товар любого бренда; списывается по партиям)."""
    await service.write_off(me.household_id, user.id, product_id, payload.quantity, payload.note, dt.date.today())
    return await service.summary(me.household_id, dt.date.today())


@router.post("/items/{product_id}/inventory", response_model=list[StockItem])
async def inventory(
    product_id: int, payload: Inventory, service: StockServiceDep, me: CurrentMemberDep, user: CurrentUserDep
):
    """Пересчитали: остаток товара становится ровно таким; «учёт сбился» снимается."""
    await service.inventory(me.household_id, user.id, product_id, payload.quantity, dt.date.today())
    return await service.summary(me.household_id, dt.date.today())


@router.patch("/items/{product_id}", response_model=list[StockItem])
async def set_flags(product_id: int, payload: ItemFlags, service: StockServiceDep, me: CurrentMemberDep):
    """«Базовый» (не учитывать остаток) и «заканчивается» (добавить в покупки)."""
    await service.set_flags(me.household_id, product_id, payload.is_staple, payload.is_low)
    return await service.summary(me.household_id, dt.date.today())


@router.get("/items/{product_id}/history", response_model=list[MovementResponse])
async def history(product_id: int, service: StockServiceDep, me: CurrentMemberDep):
    """Движения товара: покупки, готовка, съедено, списания (последние 100)."""
    return await service.history(me.household_id, product_id)

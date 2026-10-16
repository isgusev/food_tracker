"""Кассовые чеки: импорт по QR и разнесение покупок по списку и запасам."""
from __future__ import annotations


import datetime as dt

from fastapi import APIRouter

from app.api.deps import CurrentMemberDep, CurrentUserDep, ReceiptServiceDep
from app.schemas.receipt import ReceiptApply, ReceiptBrief, ReceiptCreate, ReceiptOut

router = APIRouter(prefix="/receipts", tags=["Чеки"])


@router.post("", response_model=ReceiptOut, status_code=201)
async def create(payload: ReceiptCreate, service: ReceiptServiceDep, me: CurrentMemberDep, user: CurrentUserDep):
    """Занести чек по строке из QR. Тот же QR — тот же чек. Пока ФНС не отдала чек —
    status=pending (переспрашивать GET /receipts/{id}); done — позиции с подсказками."""
    return await service.create(me.household_id, user.id, payload.qr)


@router.get("", response_model=list[ReceiptBrief])
async def recent(service: ReceiptServiceDep, me: CurrentMemberDep):
    """Последние 20 чеков семьи."""
    return await service.recent(me.household_id)


@router.get("/{receipt_id}", response_model=ReceiptOut)
async def get(receipt_id: int, service: ReceiptServiceDep, me: CurrentMemberDep):
    """Чек с позициями и подсказками; если ещё ждём ФНС — сервис переспрашивается."""
    return await service.get(me.household_id, receipt_id)


@router.post("/{receipt_id}/apply", response_model=ReceiptOut)
async def apply(
    receipt_id: int, payload: ReceiptApply, service: ReceiptServiceDep, me: CurrentMemberDep, user: CurrentUserDep
):
    """Разнести чек: list — «Куплено» строке списка, extra — покупка вне списка, skip — пропуск."""
    return await service.apply(me.household_id, user.id, receipt_id, payload, dt.date.today())

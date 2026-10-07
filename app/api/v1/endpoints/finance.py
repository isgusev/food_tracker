"""Финансы семьи: сводка за период, бюджет, цены, стоимость рецептов и кастрюль."""
from __future__ import annotations


import datetime as dt

from fastapi import APIRouter, Query

from app.api.deps import CurrentMemberDep, FinanceServiceDep
from app.schemas.finance import BudgetIn, FinanceSummary, ItemPrice, PotCost, RecipeCost

router = APIRouter(prefix="/finance", tags=["Финансы"])


@router.get("/summary", response_model=FinanceSummary)
async def summary(
    service: FinanceServiceDep,
    me: CurrentMemberDep,
    start_date: dt.date = Query(),
    end_date: dt.date = Query(),
):
    """Потрачено, ушло в еду, выброшено, траты по категориям, прогноз покупок по плану."""
    return await service.summary(me.household_id, start_date, end_date, dt.date.today())


@router.put("/budget", status_code=204)
async def set_budget(payload: BudgetIn, service: FinanceServiceDep, me: CurrentMemberDep):
    await service.set_budget(me.household_id, payload.monthly_budget)


@router.get("/prices", response_model=list[ItemPrice])
async def prices(service: FinanceServiceDep, me: CurrentMemberDep):
    """Последняя известная цена единицы каждого товара (для оценок в интерфейсе)."""
    return list((await service.prices(me.household_id)).values())


@router.get("/recipe-costs", response_model=list[RecipeCost])
async def recipe_costs(service: FinanceServiceDep, me: CurrentMemberDep):
    return await service.recipe_costs(me.household_id)


@router.get("/pot-costs", response_model=list[PotCost])
async def pot_costs(service: FinanceServiceDep, me: CurrentMemberDep):
    return await service.pot_costs(me.household_id)

"""Эндпоинты плана питания семьи: блюда, порции, «съедено»."""
from __future__ import annotations


from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentMemberDep, CurrentUserDep, PlanServiceDep
from app.schemas.plan import (
    EatOptionalWeight,
    MealItemCreate,
    MealItemMove,
    MealItemResponse,
    PortionIn,
    PortionWeightIn,
    PotSourceStatus,
    TemplateApplied,
    TemplateApply,
    TemplateResponse,
    TemplateSave,
)

router = APIRouter(prefix="/plan", tags=["План питания"])


@router.get("", response_model=list[MealItemResponse])
async def list_plan(
    service: PlanServiceDep,
    me: CurrentMemberDep,
    start_date: date = Query(),
    end_date: date = Query(),
):
    """Блюда семьи за период с порциями и КБЖУ каждой порции."""
    return await service.list_range(me.household_id, start_date, end_date)


@router.post("", response_model=MealItemResponse, status_code=201)
async def create_item(
    payload: MealItemCreate, service: PlanServiceDep, me: CurrentMemberDep, user: CurrentUserDep
):
    """Добавить блюдо (recipe_id) или готовый продукт (variant_id) с порциями по людям."""
    return await service.create(me.household_id, user.id, payload)


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(service: PlanServiceDep, me: CurrentMemberDep):
    return await service.list_templates(me.household_id)


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def save_template(payload: TemplateSave, service: PlanServiceDep, me: CurrentMemberDep):
    """Сохранить неделю (с понедельника week_start) как шаблон."""
    return await service.save_template(me.household_id, payload.name, payload.week_start)


@router.post("/templates/{template_id}/apply", response_model=TemplateApplied)
async def apply_template(
    template_id: int, payload: TemplateApply, service: PlanServiceDep, me: CurrentMemberDep, user: CurrentUserDep
):
    """Добавить блюда шаблона в неделю week_start (уже запланированное остаётся)."""
    t = await service.get_owned_template(template_id, me.household_id)
    return await service.apply_template(me.household_id, user.id, t, payload.week_start)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, service: PlanServiceDep, me: CurrentMemberDep):
    await service.delete_template(await service.get_owned_template(template_id, me.household_id))


@router.get("/pot-status/{recipe_id}", response_model=PotSourceStatus)
async def pot_status(
    recipe_id: int,
    service: PlanServiceDep,
    me: CurrentMemberDep,
    portion_g: Decimal | None = Query(default=None, gt=0, le=Decimal("99999.9")),
):
    """Есть ли блюдо в холодильнике и хватит ли свободного на portion_g (все порции блюда)."""
    return await service.pot_status(me.household_id, recipe_id, portion_g)


@router.patch("/{item_id}", response_model=MealItemResponse)
async def move_item(item_id: int, payload: MealItemMove, service: PlanServiceDep, me: CurrentMemberDep):
    """Перенести блюдо на другой день / приём пищи."""
    item = await service.get_owned_item(item_id, me.household_id)
    return await service.move(item, payload)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: int, service: PlanServiceDep, me: CurrentMemberDep):
    """Удалить блюдо; съеденное из кастрюли вернётся в неё."""
    item = await service.get_owned_item(item_id, me.household_id)
    await service.delete_item(item)


@router.post("/{item_id}/eat", response_model=MealItemResponse)
async def eat_all(item_id: int, service: PlanServiceDep, me: CurrentMemberDep):
    """«Все поели»: все несъеденные порции — съедено по плану."""
    item = await service.get_owned_item(item_id, me.household_id)
    return await service.eat_all(item)


@router.post("/{item_id}/portions", response_model=MealItemResponse, status_code=201)
async def add_portion(item_id: int, payload: PortionIn, service: PlanServiceDep, me: CurrentMemberDep):
    item = await service.get_owned_item(item_id, me.household_id)
    return await service.add_portion(item, payload)


@router.patch("/portions/{portion_id}", response_model=MealItemResponse)
async def update_portion(
    portion_id: int, payload: PortionWeightIn, service: PlanServiceDep, me: CurrentMemberDep
):
    item, portion = await service.get_owned_portion(portion_id, me.household_id)
    return await service.update_portion(item, portion, payload.weight_g)


@router.delete("/portions/{portion_id}", response_model=MealItemResponse | None)
async def delete_portion(portion_id: int, service: PlanServiceDep, me: CurrentMemberDep):
    """Убрать порцию. Если она была последней — блюдо удаляется (ответ 204)."""
    item, portion = await service.get_owned_portion(portion_id, me.household_id)
    result = await service.delete_portion(item, portion)
    return result if result is not None else Response(status_code=204)


@router.post("/portions/{portion_id}/eat", response_model=MealItemResponse)
async def eat_portion(
    portion_id: int, payload: EatOptionalWeight, service: PlanServiceDep, me: CurrentMemberDep
):
    """Съедено (вес по факту; без веса — как в плане). Списывается из кастрюли."""
    item, portion = await service.get_owned_portion(portion_id, me.household_id)
    return await service.eat_portion(item, portion, payload.weight_g)


@router.post("/portions/{portion_id}/uneat", response_model=MealItemResponse)
async def uneat_portion(portion_id: int, service: PlanServiceDep, me: CurrentMemberDep):
    """Отменить «съедено»: вес вернётся в кастрюлю."""
    item, portion = await service.get_owned_portion(portion_id, me.household_id)
    return await service.uneat_portion(item, portion)


@router.post("/portions/{portion_id}/detach", response_model=MealItemResponse)
async def detach_portion(portion_id: int, service: PlanServiceDep, me: CurrentMemberDep):
    """«Ели не из холодильника»: отвязать съеденное от кастрюли (вес в неё не возвращается)."""
    item, portion = await service.get_owned_portion(portion_id, me.household_id)
    return await service.detach_portion(item, portion)

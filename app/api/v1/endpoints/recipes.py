"""Эндпоинты рецептов и «холодильника»."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, RecipeServiceDep
from app.schemas.recipe import (
    CookingLogUpdate,
    CookingLogUpdateIngredients,
    PotArchiveItem,
    PotUsageResponse,
    RecipeCategoryCreate,
    RecipeCategoryResponse,
    RecipeCookingLogCreate,
    RecipeCookingLogResponse,
    RecipeCreate,
    RecipeResponse,
    RecipeUpdate,
)

router = APIRouter(prefix="/recipes", tags=["Рецепты и Сложные Блюда"])


@router.post("/categories", response_model=RecipeCategoryResponse, status_code=201)
async def create_recipe_category(category_in: RecipeCategoryCreate, service: RecipeServiceDep):
    return await service.create_category(category_in.name)


@router.get("/categories", response_model=list[RecipeCategoryResponse])
async def get_recipe_categories(service: RecipeServiceDep):
    return await service.list_categories()


@router.post("/", response_model=RecipeResponse, status_code=201)
async def create_recipe_template(
    recipe_in: RecipeCreate, service: RecipeServiceDep, current_user: CurrentUserDep
):
    return await service.create_recipe(current_user.id, recipe_in)


@router.get("/cooking-logs", response_model=list[RecipeCookingLogResponse])
async def get_all_cooking_logs(
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
    include_finished: bool = Query(
        default=False,
        description="True — включить в список закончившиеся кастрюли (для архива).",
    ),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Кастрюли (факты готовки) текущего пользователя — «Холодильник».

    Каждой кастрюле добавляется поле planned_g — суммарный вес планов дневника,
    привязанных к ней (сколько уже зарезервировано на приёмы пищи).
    """
    pots = await service.list_pots(
        current_user.id, limit=limit, offset=offset, include_finished=include_finished
    )
    planned = await service.pot_plan_stats(current_user.id)
    result = []
    for pot in pots:
        resp = RecipeCookingLogResponse.model_validate(pot)
        resp.planned_g = planned.get(pot.id, Decimal("0"))
        result.append(resp)
    return result


@router.get("/", response_model=list[RecipeResponse])
async def get_recipes(
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Личная библиотека рецептов текущего пользователя."""
    return await service.list_recipes(current_user.id, limit=limit, offset=offset)


@router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(recipe_id: int, service: RecipeServiceDep, current_user: CurrentUserDep):
    return await service.get_recipe(recipe_id, current_user.id)


@router.patch("/{recipe_id}", response_model=RecipeResponse)
async def update_recipe(
    recipe_id: int, payload: RecipeUpdate, service: RecipeServiceDep, current_user: CurrentUserDep
):
    """Частичное изменение шаблона рецепта (состав, название, порции и т.д.)."""
    return await service.update_recipe(recipe_id, current_user.id, payload)


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe(recipe_id: int, service: RecipeServiceDep, current_user: CurrentUserDep):
    await service.delete_recipe(recipe_id, current_user.id)


@router.post("/{recipe_id}/cook", response_model=RecipeCookingLogResponse, status_code=201)
async def cook_recipe_instance(
    recipe_id: int,
    log_in: RecipeCookingLogCreate,
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
):
    return await service.cook(current_user.id, recipe_id, log_in)


@router.get("/cooking-logs/{log_id}/usage", response_model=PotUsageResponse)
async def get_cooking_log_usage(
    log_id: int, service: RecipeServiceDep, current_user: CurrentUserDep
):
    """Даты, в которых кастрюля учтена в дневнике (прошлые / текущий+будущие)."""
    pot = await service.get_owned_pot(log_id, current_user.id)
    usage = await service.pot_diary_usage(pot, dt.date.today().isoformat())
    return PotUsageResponse(past_dates=usage["past"], current_future_dates=usage["current_future"])


@router.delete("/cooking-logs/{log_id}", status_code=204)
async def delete_cooking_log(
    log_id: int,
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
    remove_from_diary: bool = Query(
        default=False,
        description="True — удалить и связанные планы/факты текущего и будущих дней; "
                    "False — оставить их в дневнике, отвязав от кастрюли.",
    ),
):
    """Удалить приготовленное блюдо из холодильника.

    409, если блюдо учтено в дневнике за прошедшие даты (список дат в ответе).
    """
    pot = await service.get_owned_pot(log_id, current_user.id)
    await service.delete_pot_safe(pot, remove_from_diary, dt.date.today().isoformat())


@router.get("/cooking-logs/archive", response_model=list[PotArchiveItem])
async def get_pot_archive(
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
    include_deleted: bool = Query(
        default=True,
        description="Показывать ли в архиве кастрюли, помеченные удалёнными (is_discarded).",
    ),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Архив холодильника: закончившиеся блюда с логом съедания/списания."""
    return await service.list_pot_archive(
        current_user.id, include_deleted=include_deleted, limit=limit, offset=offset
    )


@router.post("/cooking-logs/{log_id}/discard", response_model=RecipeCookingLogResponse)
async def discard_cooking_log(
    log_id: int, service: RecipeServiceDep, current_user: CurrentUserDep
):
    """Пометить кастрюлю удалённой: остаток выбрасывается, запись уходит в архив.

    Физическое удаление не производится — история сохраняется; связанные планы
    дневника отвязываются и остаются «надо приготовить».
    """
    pot = await service.get_owned_pot(log_id, current_user.id)
    return await service.mark_pot_discarded(pot)


@router.patch("/cooking-logs/{log_id}", response_model=RecipeCookingLogResponse)
async def update_cooking_log_weight(
    log_id: int,
    payload: CookingLogUpdate,
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
):
    """Ручная корректировка остатка еды в кастрюле."""
    pot = await service.get_owned_pot(log_id, current_user.id)
    return await service.update_pot_remainder(pot, payload)


@router.put("/cooking-logs/{log_id}/ingredients", response_model=RecipeCookingLogResponse)
async def replace_cooking_log_ingredients(
    log_id: int,
    payload: CookingLogUpdateIngredients,
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
):
    """Полная замена фактической закладки кастрюли (добавить/убрать/заменить ингредиент)."""
    pot = await service.get_owned_pot(log_id, current_user.id)
    return await service.replace_pot_ingredients(pot, payload)

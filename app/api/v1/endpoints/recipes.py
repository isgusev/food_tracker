"""Эндпоинты рецептов и «холодильника»."""
from __future__ import annotations


from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, RecipeServiceDep
from app.schemas.recipe import (
    CookingLogUpdate,
    RecipeCategoryCreate,
    RecipeCategoryResponse,
    RecipeCookingLogCreate,
    RecipeCookingLogResponse,
    RecipeCreate,
    RecipeResponse,
)

router = APIRouter(prefix="/recipes", tags=["Рецепты и Сложные Блюда"])


@router.post("/categories", response_model=RecipeCategoryResponse, status_code=201)
async def create_recipe_category(category_in: RecipeCategoryCreate, service: RecipeServiceDep):
    return await service.create_category(category_in.name)


@router.get("/categories", response_model=list[RecipeCategoryResponse])
async def get_recipe_categories(service: RecipeServiceDep):
    return await service.list_categories()


@router.post("/", response_model=RecipeResponse, status_code=201)
async def create_recipe_template(recipe_in: RecipeCreate, service: RecipeServiceDep):
    return await service.create_recipe(recipe_in)


@router.get("/", response_model=list[RecipeResponse])
async def get_recipes(
    service: RecipeServiceDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return await service.list_recipes(limit=limit, offset=offset)


@router.post("/{recipe_id}/cook", response_model=RecipeCookingLogResponse, status_code=201)
async def cook_recipe_instance(
    recipe_id: int,
    log_in: RecipeCookingLogCreate,
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
):
    return await service.cook(current_user.id, recipe_id, log_in)


@router.get("/cooking-logs", response_model=list[RecipeCookingLogResponse])
async def get_all_cooking_logs(
    service: RecipeServiceDep,
    current_user: CurrentUserDep,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return await service.list_pots(current_user.id, limit=limit, offset=offset)


@router.delete("/cooking-logs/{log_id}", status_code=204)
async def delete_cooking_log(
    log_id: int, service: RecipeServiceDep, current_user: CurrentUserDep
):
    pot = await service.get_owned_pot(log_id, current_user.id)
    await service.delete_pot(pot)


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

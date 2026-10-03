"""Схемы рецептов и «холодильника» (Pydantic v2)."""
from __future__ import annotations


from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMModel


class RecipeCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название категории не может быть пустым")
        return v


class RecipeCategoryResponse(ORMModel):
    id: int
    name: str


class IngredientLine(BaseModel):
    """Строка ингредиентов (общая для шаблона и фактической закладки)."""

    variant_id: int
    weight_g: Decimal = Field(gt=0, le=Decimal("9999.9"))


class RecipeTemplateIngredientResponse(ORMModel):
    id: int
    variant_id: int
    weight_g: Decimal


class RecipeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    recipe_category_id: int
    cooking_time_minutes: Optional[int] = Field(default=None, ge=0)
    instructions: Optional[str] = None
    created_by_user: str = "system"
    default_servings: int = Field(default=1, ge=1, le=100)
    estimated_cooked_weight: Decimal = Field(gt=0, le=Decimal("9999.9"))
    ingredients: list[IngredientLine] = Field(min_length=1)

    @field_validator("name", "created_by_user")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Поле не может быть пустым")
        return v


class RecipeUpdate(BaseModel):
    """Изменение шаблона рецепта. Все поля опциональны — обновляем только переданные."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    recipe_category_id: Optional[int] = None
    cooking_time_minutes: Optional[int] = Field(default=None, ge=0)
    instructions: Optional[str] = None
    default_servings: Optional[int] = Field(default=None, ge=1, le=100)
    estimated_cooked_weight: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999.9"))
    ingredients: Optional[list[IngredientLine]] = Field(default=None, min_length=1)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class CookingLogUpdateIngredients(BaseModel):
    """Полная замена фактической закладки кастрюли (добавить/убрать/заменить ингредиент)."""

    ingredients: list[IngredientLine] = Field(min_length=1)


class RecipeResponse(ORMModel):
    id: int
    user_id: int
    recipe_category_id: int
    name: str
    cooking_time_minutes: Optional[int]
    instructions: Optional[str]
    created_by_user: str
    default_servings: int
    total_raw_weight: Decimal
    estimated_cooked_weight: Decimal
    calories_per_100g: Decimal
    proteins_per_100g: Decimal
    fats_per_100g: Decimal
    carbs_per_100g: Decimal
    template_ingredients: list[RecipeTemplateIngredientResponse] = []


class RecipeActualIngredientResponse(ORMModel):
    id: int
    variant_id: int
    weight_g: Decimal


class RecipeCookingLogCreate(BaseModel):
    # user_id берётся из JWT — см. endpoints/recipes.py
    total_cooked_weight: Decimal = Field(gt=0, le=Decimal("9999.9"))
    ingredients: list[IngredientLine] = Field(min_length=1)


class RecipeCookingLogResponse(ORMModel):
    id: int
    recipe_id: Optional[int]
    user_id: int
    cooked_at: Optional[datetime] = None
    total_raw_weight: Decimal
    total_cooked_weight: Decimal
    current_remaining_weight: Decimal
    is_finished: bool
    calories_per_100g: Decimal
    proteins_per_100g: Decimal
    fats_per_100g: Decimal
    carbs_per_100g: Decimal
    actual_ingredients: list[RecipeActualIngredientResponse] = []


class CookingLogUpdate(BaseModel):
    """Ручная корректировка остатка в кастрюле (замена «сырого» dict-payload)."""

    current_remaining_weight: Decimal = Field(ge=0, le=Decimal("9999.9"))


class PotUsageResponse(BaseModel):
    """Использование кастрюли в дневнике: разделённое по датам."""

    past_dates: list[str] = []           # учтено в прошедших днях → удаление запрещено
    current_future_dates: list[str] = []  # текущий/будущие дни → спрашиваем пользователя

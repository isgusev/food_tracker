"""Схемы плана питания семьи и списка покупок (Pydantic v2)."""
from __future__ import annotations


from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain import MEAL_TYPES

PortionWeight = Field(gt=0, le=Decimal("2000"))


class PortionIn(BaseModel):
    """Порция при планировании. member_id = None — гость."""

    member_id: Optional[int] = None
    weight_g: Decimal = PortionWeight


class MealItemCreate(BaseModel):
    date_day: date_type
    meal_type: str
    # Ровно одно из двух: блюдо по рецепту ИЛИ готовый продукт (версия КБЖУ)
    recipe_id: Optional[int] = None
    variant_id: Optional[int] = None
    portions: list[PortionIn] = Field(min_length=1, max_length=30)

    @field_validator("meal_type")
    @classmethod
    def _valid_meal(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in MEAL_TYPES:
            raise ValueError(f"meal_type должен быть одним из {sorted(MEAL_TYPES)}")
        return v

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if (self.recipe_id is None) == (self.variant_id is None):
            raise ValueError("Укажите либо recipe_id (блюдо), либо variant_id (готовый продукт)")
        member_ids = [p.member_id for p in self.portions if p.member_id is not None]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("У каждого члена семьи — одна порция в блюде")
        return self


class MealItemMove(BaseModel):
    date_day: Optional[date_type] = None
    meal_type: Optional[str] = None

    @field_validator("meal_type")
    @classmethod
    def _valid_meal(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in MEAL_TYPES:
            raise ValueError(f"meal_type должен быть одним из {sorted(MEAL_TYPES)}")
        return v


class PortionWeightIn(BaseModel):
    weight_g: Decimal = PortionWeight


class EatOptionalWeight(BaseModel):
    """«Съедено»: вес по факту; не задан — как в плане."""

    weight_g: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("2000"))


class Macros(BaseModel):
    calories: Decimal = Decimal("0.0")
    proteins: Decimal = Decimal("0.0")
    fats: Decimal = Decimal("0.0")
    carbs: Decimal = Decimal("0.0")


class PortionResponse(Macros):
    id: int
    member_id: Optional[int]
    member_name: Optional[str] = None  # None — гость
    weight_g: Decimal
    is_eaten: bool
    eaten_from_pot_id: Optional[int] = None


class MealItemResponse(BaseModel):
    id: int
    date_day: date_type
    meal_type: str
    kind: str                         # "recipe" | "product"
    recipe_id: Optional[int] = None
    variant_id: Optional[int] = None
    name: str
    # "product" | "to_cook" | "in_fridge"
    state: str
    cooking_log_id: Optional[int] = None
    portions: list[PortionResponse]

    # Холодильник для рецептов: остаток кастрюли (привязанной или активной по
    # рецепту), сколько из неё уже зарезервировано и хватает ли на это блюдо
    fridge_pot_id: Optional[int] = None
    fridge_available_g: Optional[Decimal] = None
    fridge_reserved_g: Optional[Decimal] = None
    fridge_enough: Optional[bool] = None

    total_weight_g: Decimal           # вес всех несъеденных + съеденных порций
    remaining_weight_g: Decimal       # ещё не съедено


class PotSourceStatus(BaseModel):
    """Статус холодильника при планировании: есть ли кастрюля и сколько в ней свободно."""

    has_active_pot: bool = False
    pot_id: Optional[int] = None
    available_g: Decimal = Decimal("0")
    planned_g: Decimal = Decimal("0")
    enough_for_portion: Optional[bool] = None

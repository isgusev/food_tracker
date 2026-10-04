"""Схемы дневника питания (Pydantic v2)."""
from __future__ import annotations


import re
from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain import MEAL_TYPES
from app.schemas.common import ORMModel

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DiaryLogCreate(BaseModel):
    # user_id берётся из JWT (endpoints внедряют текущего пользователя) —
    # клиент не может создать запись от чужого имени
    date_day: str  # ISO-дата "YYYY-MM-DD" — формат согласован с фильтром в SQL
    meal_type: str
    recipe_id: int
    weight_g: Decimal = Field(gt=0, le=Decimal("999.9"))
    servings_multiplier: int = Field(default=1, ge=1, le=10)

    @field_validator("servings_multiplier")
    @classmethod
    def _valid_people(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError("Количество человек должно быть от 1 до 10")
        return v

    @field_validator("date_day")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        v = v.strip()
        if not _DATE_RE.match(v):
            raise ValueError("date_day должен быть в формате YYYY-MM-DD")
        date_type.fromisoformat(v)  # проверка календарной валидности
        return v

    @field_validator("meal_type")
    @classmethod
    def _valid_meal(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in MEAL_TYPES:
            raise ValueError(f"meal_type должен быть одним из {sorted(MEAL_TYPES)}")
        return v

    @model_validator(mode="after")
    def _negative_scale_requires_flag(self):
        # Отрицательный множитель означает «масштабировать всем пропорционально»;
        # флаг scale_all_proportions должен ставиться явно на уровне сервиса/UI.
        return self


class DiaryLogUpdateWeight(BaseModel):
    weight_g: Decimal = Field(gt=0, le=Decimal("999.9"))


class DiaryLogResponse(ORMModel):
    id: int
    user_id: int
    date_day: str
    meal_type: str
    status: str
    recipe_id: Optional[int]
    cooking_log_id: Optional[int]
    weight_g: Decimal
    servings_multiplier: Optional[int] = 1

    # Поля, наполняемые сервисом для UI (КБЖУ порции)
    recipe_name: Optional[str] = None
    calories: Decimal = Decimal("0.0")
    proteins: Decimal = Decimal("0.0")
    fats: Decimal = Decimal("0.0")
    carbs: Decimal = Decimal("0.0")

    # Инфостатус источника блюда (наполняет сервис; см. compute_source_status)
    source_status: Optional[str] = None       # "fridge" | "not_cooked" | "detached"
    fridge_pot_id: Optional[int] = None       # активная кастрюля этого рецепта
    fridge_available_g: Optional[Decimal] = None   # остаток в кастрюле
    fridge_planned_g: Optional[Decimal] = None     # уже зарезервировано планами
    fridge_enough: Optional[bool] = None      # хватает ли остатка на ЭТУ порцию


class PotSourceStatus(BaseModel):
    """Ответ эндпоинта /diary/pot-status/{recipe_id} — статус холодильника при планировании."""

    has_active_pot: bool = False
    pot_id: Optional[int] = None
    available_g: Decimal = Decimal("0")
    planned_g: Decimal = Decimal("0")
    enough_for_portion: Optional[bool] = None


class ShoppingListItem(BaseModel):
    variant_id: int
    product_name: str
    weight_g: Decimal


class ShoppingListResponse(BaseModel):
    start_date: date_type
    end_date: date_type
    items: list[ShoppingListItem]

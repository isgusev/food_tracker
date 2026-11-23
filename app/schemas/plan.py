"""Схемы плана питания семьи и списка покупок (Pydantic v2)."""
from __future__ import annotations


from datetime import date as date_type
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import meal_list, meal_type

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
    exact: bool = False   # готовый продукт: в покупки «именно этот вариант», а не любой бренд товара
    portions: list[PortionIn] = Field(min_length=1, max_length=30)

    @field_validator("meal_type")
    @classmethod
    def _valid_meal(cls, v: str) -> str:
        return meal_type(v)

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
    pinned: Optional[bool] = None     # «📌 закреплено»: перегенерация не трогает (блюдо остаётся auto)

    @field_validator("meal_type")
    @classmethod
    def _valid_meal(cls, v: Optional[str]) -> Optional[str]:
        return meal_type(v)


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
    exact: bool = False
    name: str
    # "product" | "to_cook" | "in_fridge"
    state: str
    cooking_log_id: Optional[int] = None
    portions: list[PortionResponse]
    origin: str = "manual"            # manual | auto (предложено автопланом)
    pinned: bool = False
    auto_reason: Optional[str] = None

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


class TemplateSave(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    week_start: date_type          # понедельник недели, которую сохраняем


class TemplateApply(BaseModel):
    week_start: date_type          # понедельник недели, куда применяем


class TemplateResponse(BaseModel):
    id: int
    name: str
    items_count: int
    meals_per_day: dict[int, int]  # день недели (0 = пн) → сколько блюд


class TemplateApplied(BaseModel):
    created: int
    skipped: int                   # блюда, чей рецепт/продукт уже удалён


class TypicalPortion(BaseModel):
    """Типичная порция едока (docs/AUTOPLAN.md, 3.5)."""

    member_id: int
    weight_g: Decimal
    source: str   # history — по съеденному · family — по другим членам семьи · recipe — порция рецепта · target — по цели ккал


class BatchCheck(BaseModel):
    """Хватит ли закладки рецепта под блюдо (подсказка в форме плана).

    status: pot — блюдо возьмёт готовое из холодильника; ok — остаток после готовки 0 или от порции и больше;
    leftover — останется меньше порции (leftover г); short — не хватит в пределах допуска, при готовке порции
    уменьшатся; none — проверять нечего (у рецепта нет выхода). Считается вместе с другими неприготовленными
    блюдами этого рецепта, пока закладка свежая (± keeps_days − 1 дней) — как в покупках (`batches_for`).
    target — сколько граммов дать этому блюду, чтобы съесть закладки целиком."""

    status: Literal["pot", "ok", "leftover", "short", "none"]
    cooked: Decimal = Decimal(0)          # выход одной закладки
    batches: Decimal = Decimal(0)
    planned: Decimal = Decimal(0)         # это блюдо
    others: Decimal = Decimal(0)          # другие блюда той же закладки
    leftover: Decimal = Decimal(0)        # < 0 — нехватка
    portion: Optional[Decimal] = None     # порция рецепта (выход / порций)
    target: Decimal = Decimal(0)


class AutofillIn(BaseModel):
    start: date_type
    end: date_type
    meal_types: Optional[list[str]] = None   # какие приёмы заполнять; None — из настроек семьи (все)
    dry_run: bool = False
    cook: bool = True   # false — только остатки и заготовки (без новых готовок)

    @field_validator("meal_types")
    @classmethod
    def _meals(cls, v):
        return meal_list(v, empty_is_any=False)

    @model_validator(mode="after")
    def _period(self):
        if self.end < self.start:
            raise ValueError("Конец периода раньше начала")
        if (self.end - self.start).days > 31:
            raise ValueError("Не больше месяца за раз")
        return self


class AutofillPortion(BaseModel):
    member_id: int
    weight_g: Decimal


class AutofillSuggestion(BaseModel):
    """Что автоплан поставил (или поставил бы при dry_run) в пустую ячейку."""

    date_day: date_type
    meal_type: str
    recipe_id: Optional[int] = None
    variant_id: Optional[int] = None    # регулярный готовый продукт (этап 3)
    name: str
    cooking_log_id: Optional[int] = None
    portions: list[AutofillPortion]
    auto_reason: str
    # fridge — остаток в холодильнике · freezer — заготовка · cook — приготовить · continue — та же закладка ·
    # regular — обычный готовый продукт в пустой ячейке · side — он же к предложенному блюду
    source: str = "fridge"
    item_id: Optional[int] = None   # id созданного блюда (не при dry_run)


class AutofillOut(BaseModel):
    items: list[AutofillSuggestion]
    replaced: int = 0               # сколько прежних предложений убрано (перегенерация)
    dry_run: bool = False


class AcceptIn(BaseModel):
    start: date_type
    end: date_type


    @model_validator(mode="after")
    def _period(self):
        if self.end < self.start:
            raise ValueError("Конец периода раньше начала")
        return self


class AcceptOut(BaseModel):
    accepted: int

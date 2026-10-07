"""Схемы финансов семьи (Pydantic v2)."""
from __future__ import annotations


from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ItemPrice(BaseModel):
    item_key: str
    unit: str
    unit_price: Decimal     # ₽ за единицу товара (г / мл / шт)
    as_of: date


class PotCost(BaseModel):
    pot_id: int
    cost: Optional[Decimal] = None
    per_100g: Optional[Decimal] = None
    complete: bool          # все ингредиенты списаны из партий с ценой


class RecipeCost(BaseModel):
    recipe_id: int
    total: Optional[Decimal] = None
    per_portion: Optional[Decimal] = None
    per_100g: Optional[Decimal] = None
    priced_share: Decimal   # доля состава (по весу) с известной ценой, 0..1


class CategorySpend(BaseModel):
    name: str
    spent: Decimal


class WasteItem(BaseModel):
    name: str
    value: Decimal
    reason: str


class FinanceSummary(BaseModel):
    start_date: date
    end_date: date
    spent: Decimal
    unpriced_purchases: int
    by_category: list[CategorySpend]
    eaten_value: Decimal
    wasted_value: Decimal
    waste: list[WasteItem]
    monthly_budget: Optional[Decimal] = None
    planned_to_buy: Decimal          # оценка: что ещё купить по плану до конца периода
    planned_unknown: int             # позиций без известной цены


class BudgetIn(BaseModel):
    monthly_budget: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))

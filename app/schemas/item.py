"""Схемы товаров — базовых наименований без бренда (Pydantic v2)."""
from __future__ import annotations


from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ItemProductOut(BaseModel):
    id: int
    name: str
    brand: Optional[str] = None
    base_unit: str
    packages: list[Decimal] = []


class ItemOut(BaseModel):
    key: str
    name: str
    unit: str
    products: list[ItemProductOut]


class ItemSuggestion(BaseModel):
    """Похоже на один товар: предлагаемое название и товары группы."""

    name: str
    items: list[ItemOut]


def _clean(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Название не может быть пустым")
    return v


class ItemMerge(BaseModel):
    keys: list[str] = Field(min_length=2, max_length=50)   # первый — в него сливаем
    name: Optional[str] = Field(default=None, max_length=255)


class ItemRename(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _clean(v)


class ProductItemMove(BaseModel):
    """Перенести продукт в существующий товар (item_key) или выделить в новый (new_name)."""

    item_key: Optional[str] = Field(default=None, max_length=255)
    new_name: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _one(self):
        if not self.item_key and not (self.new_name and self.new_name.strip()):
            raise ValueError("Укажите item_key или new_name")
        return self

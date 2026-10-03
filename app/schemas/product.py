"""Схемы каталога продуктов (Pydantic v2): строгая валидация на границе API."""
from __future__ import annotations


from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMModel

MAX_WEIGHT_PRECISION = 4  # Numeric(5,1) в БД — до 9999.9 г


class ProductVariantCreate(BaseModel):
    manufacturer_name: Optional[str] = None  # get-or-create логика на уровне сервиса
    calories: Decimal = Field(ge=0, le=9999)
    proteins: Decimal = Field(ge=0, le=999)
    fats: Decimal = Field(ge=0, le=999)
    carbs: Decimal = Field(ge=0, le=999)

    @field_validator("manufacturer_name")
    @classmethod
    def _strip_manufacturer(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v and v.strip() else None


class ProductWithCategoryCreate(BaseModel):
    """Создание продукта с авто-созданием категории по имени (для UI)."""

    category_name: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    brand_name: Optional[str] = None
    base_variant: ProductVariantCreate

    @field_validator("category_name", "name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Поле не может быть пустым")
        return v


class ProductVariantResponse(ORMModel):
    id: int
    manufacturer_id: int
    calories: Decimal
    proteins: Decimal
    fats: Decimal
    carbs: Decimal
    wrong_nutrients: bool
    version: int
    is_active: bool


class ManufacturerResponse(ORMModel):
    id: int
    product_id: int
    name: Optional[str] = None
    variants: list[ProductVariantResponse] = []


class BrandResponse(ORMModel):
    id: int
    name: str


class ProductCreate(ORMModel):
    category_id: int
    name: str = Field(min_length=1, max_length=255)
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    base_variant: ProductVariantCreate

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название продукта не может быть пустым")
        return v

    @model_validator(mode="after")
    def _brand_required(self):
        if self.brand_id is None and not (self.brand_name and self.brand_name.strip()):
            raise ValueError("Укажите либо brand_id, либо brand_name")
        return self


class ProductResponse(ORMModel):
    id: int
    category_id: int
    name: str
    brand: BrandResponse
    is_verified: bool
    manufacturers: list[ManufacturerResponse] = []


class CategoryCreate(ORMModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название категории не может быть пустым")
        return v


class CategoryResponse(ORMModel):
    id: int
    name: str

"""Схемы запасов и общего списка покупок (Pydantic v2)."""
from __future__ import annotations


from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

Qty = Field(gt=0, le=Decimal("9999999.9"))


class LotAdd(BaseModel):
    """Добавить в запасы (покупка мимо списка, подарили, нашли в шкафу)."""

    product_id: int
    variant_id: Optional[int] = None
    quantity: Decimal = Qty                  # в базовой единице продукта
    price: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))
    purchased_on: Optional[date] = None
    expires_on: Optional[date] = None


class WriteOff(BaseModel):
    quantity: Decimal = Qty
    note: Optional[str] = Field(default=None, max_length=200)


class Inventory(BaseModel):
    quantity: Decimal = Field(ge=0, le=Decimal("9999999.9"))  # сколько есть на самом деле


class ItemFlags(BaseModel):
    is_staple: Optional[bool] = None
    is_low: Optional[bool] = None


class LotResponse(BaseModel):
    id: int
    product_id: int
    brand: Optional[str] = None
    variant_id: Optional[int] = None
    quantity: Decimal
    remaining: Decimal
    price: Optional[Decimal] = None
    purchased_on: date
    expires_on: Optional[date] = None
    source: str


class StockItem(BaseModel):
    """Товар в запасах (все бренды вместе)."""

    item_key: str
    product_id: int
    name: str
    category_name: Optional[str] = None
    unit: str
    piece_weight_g: Optional[Decimal] = None
    remaining: Decimal
    expired: Decimal
    nearest_expiry: Optional[date] = None
    is_staple: bool
    is_low: bool
    needs_check: bool
    lots: list[LotResponse]


class MovementResponse(BaseModel):
    id: int
    delta: Decimal
    reason: str
    lot_id: Optional[int] = None
    pot_id: Optional[int] = None
    portion_id: Optional[int] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None


class ShoppingItem(BaseModel):
    """Расчётная позиция списка покупок (по товару)."""

    item_key: str
    product_id: int
    variant_id: Optional[int] = None
    product_name: str
    brand: Optional[str] = None
    category_name: Optional[str] = None
    unit: str
    need: Optional[Decimal] = None        # нужно на период
    in_stock: Optional[Decimal] = None    # свободно в запасах
    to_buy: Optional[Decimal] = None      # купить
    package_amount: Optional[Decimal] = None
    package_count: Optional[int] = None
    is_staple: bool = False


class ShoppingPreview(BaseModel):
    start_date: date
    end_date: date
    items: list[ShoppingItem]


class ListGenerate(BaseModel):
    start_date: date
    end_date: date


class ExtraLine(BaseModel):
    product_id: int
    quantity: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999999.9"))


class LineCheck(BaseModel):
    """«Куплено»: всё необязательно — по умолчанию предложенные упаковки."""

    quantity: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999999.9"))
    price: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))
    variant_id: Optional[int] = None
    expires_on: Optional[date] = None


class LineUpdate(BaseModel):
    quantity: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999999.9"))
    price: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))
    variant_id: Optional[int] = None
    expires_on: Optional[date] = None


class ShoppingLineResponse(BaseModel):
    id: int
    item_key: Optional[str] = None
    product_id: int
    variant_id: Optional[int] = None
    product_name: str
    brand: Optional[str] = None
    category_name: Optional[str] = None
    unit: str
    needed: Optional[Decimal] = None
    package_amount: Optional[Decimal] = None
    package_count: Optional[int] = None
    is_extra: bool
    is_staple: bool
    is_checked: bool
    checked_at: Optional[datetime] = None
    bought_quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    expires_on: Optional[date] = None
    lot_variant_id: Optional[int] = None


class ShoppingListOut(BaseModel):
    id: int
    start_date: date
    end_date: date
    status: str
    updated_at: Optional[datetime] = None
    lines: list[ShoppingLineResponse]

"""Схемы запасов и общего списка покупок (Pydantic v2)."""
from __future__ import annotations


from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

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
    # «Обычно берём»: auto — по статистике, always — всегда предлагать, never — не предлагать
    regular: Optional[Literal["auto", "always", "never"]] = None
    regular_qty: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999"))   # своё кол-во в неделю; 0 — сбросить
    is_snack: Optional[bool] = None


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
    regular: str = "auto"
    regular_qty: Optional[Decimal] = None
    is_snack: bool = False
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
    is_exact: bool = False                # «именно этот вариант» — строка с брендом


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
    # купили другой бренд того же товара (строка «Кефир 3,2%» — взяли «Простоквашино»)
    product_id: Optional[int] = None


class LineUpdate(BaseModel):
    quantity: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999999.9"))
    price: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))
    variant_id: Optional[int] = None
    expires_on: Optional[date] = None
    product_id: Optional[int] = None      # какой бренд товара купили на самом деле


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
    is_exact: bool = False
    added: Optional[Decimal] = None       # из них добавлено вручную (поверх плана)
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


# --- Пачки с кодами «Честного знака» ---
class PackIn(BaseModel):
    """Одна пачка: срок годности (из кода или введённый) и код маркировки, если сканировали."""

    expires_on: Optional[date] = None
    code: Optional[str] = Field(default=None, max_length=300)


class PacksAdd(BaseModel):
    """Добавить в запасы по пачкам: пачки с разным сроком станут разными партиями."""

    product_id: int
    variant_id: Optional[int] = None
    pack_amount: Decimal = Qty               # сколько в одной пачке, в базовой единице
    price: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))  # за все пачки
    purchased_on: Optional[date] = None
    packs: list[PackIn] = Field(min_length=1, max_length=200)


class PacksSplit(BaseModel):
    """Разложить уже купленную партию по пачкам со своими сроками."""

    pack_amount: Decimal = Qty
    packs: list[PackIn] = Field(min_length=1, max_length=200)


class MarkParseIn(BaseModel):
    code: str = Field(min_length=10, max_length=300)


class MarkParsed(BaseModel):
    """Что удалось прочитать из кода маркировки."""

    gtin: str
    barcode: str                             # EAN-13, как в справочнике
    serial: str
    expires_on: Optional[date] = None
    product_id: Optional[int] = None         # товар справочника с этим штрихкодом
    product_name: Optional[str] = None
    already_registered: bool = False         # эта пачка уже в запасах


class RegularItem(BaseModel):
    """«Обычно берём»: товар, который покупают почти каждую неделю (docs/AUTOPLAN.md, 5)."""

    item_key: str
    product_id: int                 # обычный бренд (последняя покупка)
    name: str
    unit: str
    weekly: Decimal                 # сколько в неделю (медиана или своё)
    to_buy: Decimal                 # на период минус запасы и то, что уже в списке
    package_amount: Optional[Decimal] = None
    package_count: Optional[int] = None
    weeks_bought: int               # из скольких последних недель покупали
    weeks: int = 8
    always: bool = False            # «всегда предлагать»
    is_snack: bool = False
    est_price: Optional[Decimal] = None


class SnackQuota(BaseModel):
    spent: Decimal = Decimal("0")   # потрачено на снеки за неделю (с понедельника)
    quota: Optional[Decimal] = None # квота ₽/неделю; None — не задана
    hidden: int = 0                 # снеков не предложено: квота кончилась


class RegularOut(BaseModel):
    items: list[RegularItem]
    snacks: SnackQuota

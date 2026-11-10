"""Схемы импорта кассовых чеков по QR (Pydantic v2)."""
from __future__ import annotations


from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

Action = Literal["list", "extra", "skip"]


class ReceiptCreate(BaseModel):
    """Строка из QR чека: «t=20261016T1923&s=1498.00&fn=…&i=…&fp=…&n=1» (или ссылка)."""

    qr: str = Field(min_length=1, max_length=500)


class Suggestion(BaseModel):
    """Что сделать со строкой чека.

    action: list — отметить строку списка покупок купленной; extra — куплен продукт
    не из списка; skip — пропустить (не еда, не узнали).
    source: alias — выучено по прошлым чекам; list — строка списка; catalog — справочник; none.
    """

    action: Action
    source: Literal["alias", "list", "catalog", "none"]
    confidence: float
    shopping_line_id: Optional[int] = None
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    brand: Optional[str] = None
    unit: Optional[str] = None
    quantity: Optional[Decimal] = None   # в базовой единице продукта (г / мл / шт)


class ReceiptItemOut(BaseModel):
    index: int
    name: str
    quantity: Decimal          # как в чеке: штук или кг для весового
    price: Decimal
    sum: Decimal
    suggestion: Optional[Suggestion] = None


class ReceiptOut(BaseModel):
    id: int
    status: Literal["pending", "done", "error", "applied"]
    error: Optional[str] = None
    store_name: Optional[str] = None
    store_inn: Optional[str] = None
    purchased_at: Optional[datetime] = None
    total: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    items: list[ReceiptItemOut] = []


class ReceiptBrief(BaseModel):
    id: int
    status: str
    store_name: Optional[str] = None
    purchased_at: Optional[datetime] = None
    total: Optional[Decimal] = None
    items_count: int
    created_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


class ApplyLine(BaseModel):
    index: int = Field(ge=0)
    action: Action
    shopping_line_id: Optional[int] = None
    product_id: Optional[int] = None
    quantity: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999999.9"))
    price: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"))


class ReceiptApply(BaseModel):
    lines: list[ApplyLine] = Field(max_length=500)

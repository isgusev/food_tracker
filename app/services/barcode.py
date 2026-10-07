"""Поиск продукта по штрихкоду: свой справочник → Open Food Facts.

Open Food Facts — открытая база упаковок с КБЖУ на 100 г. Мы только
подсказываем: пользователь проверяет цифры и сохраняет продукт сам.
"""
from __future__ import annotations


import re
from decimal import Decimal, InvalidOperation

import httpx

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "product_name,product_name_ru,brands,nutriments,quantity,categories_tags"
BARCODE_RE = re.compile(r"^\d{8,14}$")


async def fetch_off(code: str) -> dict | None:
    """Сырой ответ Open Food Facts (None — не найдено или сеть недоступна)."""
    try:
        async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "FoodTracker/1.0 (family meal planner)"}) as client:
            r = await client.get(OFF_URL.format(code=code), params={"fields": OFF_FIELDS})
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("product") if data.get("status") == 1 else None
    except (httpx.HTTPError, ValueError):
        return None


def _num(v) -> Decimal | None:
    try:
        return Decimal(str(v)).quantize(Decimal("0.1")) if v is not None else None
    except (InvalidOperation, ValueError):
        return None


_QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|кг|g|г|гр|l|л|ml|мл|cl|шт|pcs)\b", re.IGNORECASE)


def parse_quantity(text: str | None) -> tuple[str | None, Decimal | None]:
    """«930 ml» → ("ml", 930); «1 кг» → ("g", 1000); «10 шт» → ("pcs", 10)."""
    if not text:
        return None, None
    m = _QTY_RE.search(text)
    if not m:
        return None, None
    value = Decimal(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    if unit in ("kg", "кг"):
        return "g", value * 1000
    if unit in ("g", "г", "гр"):
        return "g", value
    if unit in ("l", "л"):
        return "ml", value * 1000
    if unit == "cl":
        return "ml", value * 10
    if unit in ("ml", "мл"):
        return "ml", value
    return "pcs", value


def parse_off(product: dict) -> dict:
    n = product.get("nutriments") or {}
    unit, amount = parse_quantity(product.get("quantity"))
    return {
        "name": (product.get("product_name_ru") or product.get("product_name") or "").strip() or None,
        "brand": (product.get("brands") or "").split(",")[0].strip() or None,
        "calories": _num(n.get("energy-kcal_100g")),
        "proteins": _num(n.get("proteins_100g")),
        "fats": _num(n.get("fat_100g")),
        "carbs": _num(n.get("carbohydrates_100g")),
        "package_unit": unit,
        "package_amount": amount,
    }

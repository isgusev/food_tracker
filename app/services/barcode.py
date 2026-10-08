"""Open Food Facts: поиск упаковки по штрихкоду и по названию.

Open Food Facts — открытая база упаковок с КБЖУ на 100 г. Мы только
подсказываем: пользователь проверяет цифры и сохраняет продукт сам.
"""
from __future__ import annotations


import html
import re
import time
from decimal import Decimal, InvalidOperation

import httpx

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
# Классический поиск ищет все слова сразу («творог простоквашино» → творог этого бренда);
# новый search-a-licious быстрее, но ищет «любое из слов» — он запасной
OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_SEARCH_FALLBACK_URL = "https://search.openfoodfacts.org/search"
OFF_FIELDS = (
    "code,product_name,product_name_ru,brands,brand_owner,nutriments,"
    "quantity,product_quantity,product_quantity_unit,categories_tags"
)
HEADERS = {"User-Agent": "FoodTracker/1.0 (family meal planner)"}
BARCODE_RE = re.compile(r"^\d{8,14}$")

# У OFF лимит ~10 поисков в минуту с одного адреса — одинаковые запросы
# отдаём из памяти процесса (семья часто ищет одно и то же)
_SEARCH_TTL = 600.0
_search_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}


async def fetch_off(code: str) -> dict | None:
    """Сырой ответ Open Food Facts (None — не найдено или сеть недоступна)."""
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=HEADERS) as client:
            r = await client.get(OFF_URL.format(code=code), params={"fields": OFF_FIELDS})
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("product") if data.get("status") == 1 else None
    except (httpx.HTTPError, ValueError):
        return None


async def search_off(query: str, limit: int = 20) -> list[dict] | None:
    """Сырые продукты OFF по названию/бренду (None — сервис недоступен)."""
    key = (query.strip().lower(), limit)
    hit = _search_cache.get(key)
    if hit and time.monotonic() - hit[0] < _SEARCH_TTL:
        return hit[1]
    products = await _search_classic(query, limit)
    if products is None:
        products = await _search_new(query, limit)
    if products is not None:
        if len(_search_cache) > 500:
            _search_cache.clear()
        _search_cache[key] = (time.monotonic(), products)
    return products


async def _search_classic(query: str, limit: int) -> list[dict] | None:
    params = {
        "search_terms": query, "search_simple": 1, "json": 1, "page_size": limit,
        "sort_by": "unique_scans_n", "fields": OFF_FIELDS,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=HEADERS) as client:
            r = await client.get(OFF_SEARCH_URL, params=params)
        if r.status_code != 200:
            return None
        return list(r.json().get("products") or [])
    except (httpx.HTTPError, ValueError):
        return None


async def _search_new(query: str, limit: int) -> list[dict] | None:
    params = {"q": query, "langs": "ru", "page_size": limit, "fields": OFF_FIELDS}
    try:
        async with httpx.AsyncClient(timeout=6.0, headers=HEADERS) as client:
            r = await client.get(OFF_SEARCH_FALLBACK_URL, params=params)
        if r.status_code != 200:
            return None
        hits = list(r.json().get("hits") or [])
        for h in hits:  # здесь бренды — списком, в классическом API — строкой
            if isinstance(h.get("brands"), list):
                h["brands"] = ", ".join(h["brands"])
        return hits
    except (httpx.HTTPError, ValueError):
        return None


def _num(v) -> Decimal | None:
    try:
        return Decimal(str(v)).quantize(Decimal("0.1")) if v is not None and v != "" else None
    except (InvalidOperation, ValueError):
        return None


def _text(v) -> str | None:
    if not isinstance(v, str):
        return None
    v = " ".join(html.unescape(v).split())
    return v or None


_QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|кг|g|г|гр|l|л|ml|мл|cl|шт|pcs)(?![a-zа-я])", re.IGNORECASE)


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


def _package(product: dict) -> tuple[str | None, Decimal | None]:
    """Упаковка: числовые поля OFF, иначе разбор строки «quantity»."""
    amount = _num(product.get("product_quantity"))
    unit = (product.get("product_quantity_unit") or "").lower()
    if amount and amount > 0 and unit in ("g", "ml"):
        return unit, amount
    return parse_quantity(_text(product.get("quantity")))


def parse_off(product: dict) -> dict:
    n = product.get("nutriments") or {}
    unit, amount = _package(product)
    brand = (_text(product.get("brands")) or "").split(",")[0].strip() or None
    owner = _text(product.get("brand_owner"))
    code = str(product.get("code") or "")
    return {
        "barcode": code if BARCODE_RE.match(code) else None,
        "name": _text(product.get("product_name_ru")) or _text(product.get("product_name")),
        "brand": brand,
        # производитель — только если отличается от бренда (владелец марки)
        "manufacturer": owner if owner and (not brand or owner.lower() != brand.lower()) else None,
        "calories": _num(n.get("energy-kcal_100g")),
        "proteins": _num(n.get("proteins_100g")),
        "fats": _num(n.get("fat_100g")),
        "carbs": _num(n.get("carbohydrates_100g")),
        "package_unit": unit,
        "package_amount": amount if amount and amount > 0 else None,
    }

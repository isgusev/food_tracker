"""Open Food Facts: поиск упаковки по штрихкоду и по названию.

Open Food Facts — открытая база упаковок с КБЖУ на 100 г. Мы только
подсказываем: пользователь проверяет цифры и сохраняет продукт сам.
"""
from __future__ import annotations


import asyncio
import html
import re
import time
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

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
_search_cache: dict[tuple, tuple[float, list[dict]]] = {}

# Ограничения OFF, которые обходим у себя:
#  * классический поиск ищет только ЦЕЛЫЕ слова: «пита лива» и «пита леванская» → 0;
#  * он часто отвечает 503 (лимит) — тогда остаётся search-a-licious, а у него
#    неполный индекс и поиск «любое из слов» без учёта опечаток.
# Поэтому: точный запрос → если мало, запрос без последнего (недописанного) слова →
# при необходимости search-a-licious; всё вместе ранжируем у себя по похожести
# (целое слово > начало слова > слово с опечаткой).
_MIN_GOOD = 5


def normalize_query(text: str) -> str:
    """Нижний регистр, ё→е, без кавычек и знаков: «Пита "Ливанская» → «пита ливанская»."""
    text = html.unescape(text or "").lower().replace("ё", "е")
    return " ".join(re.sub(r"[^\w%.,]+|(?<!\d)[.,]|[.,](?!\d)", " ", text).split())


async def search_off(query: str, limit: int = 20) -> list[dict] | None:
    """Сырые продукты OFF по названию/бренду, лучшие совпадения — первыми
    (None — сервис недоступен)."""
    q = normalize_query(query)
    words = q.split()
    if not words:
        return []
    pool: list[dict] = []
    answered = False

    exact = await _cached(("classic", q, 50), lambda: _search_classic(q, 50))
    if exact is not None:
        answered = True
        pool += exact
    # упёрлись в лимит OFF — второй классический запрос тоже не пройдёт, не ждём его
    if exact is not None and len(pool) < _MIN_GOOD and len(words) >= 2:
        # последнее слово недописано или с опечаткой — берём шире и ранжируем сами
        broad_q = " ".join(words[:-1])
        broad = await _cached(("classic", broad_q, 100), lambda: _search_classic(broad_q, 100))
        if broad is not None:
            answered = True
            pool += broad
    if len(rank_products(pool, q, limit)) < _MIN_GOOD:
        extra = await _cached(("new", q, 50), lambda: _search_new(q, 50))
        if extra is not None:
            answered = True
            pool += extra
    if not answered:
        return None
    return rank_products(pool, q, limit)


async def fetch_off(code: str) -> dict | None:
    """Сырой ответ Open Food Facts по штрихкоду (None — не найдено или сеть недоступна)."""
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=HEADERS) as client:
            r = await client.get(OFF_URL.format(code=code), params={"fields": OFF_FIELDS})
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("product") if data.get("status") == 1 else None
    except (httpx.HTTPError, ValueError):
        return None


async def _cached(key: tuple, fetch) -> list[dict] | None:
    hit = _search_cache.get(key)
    if hit and time.monotonic() - hit[0] < _SEARCH_TTL:
        return hit[1]
    result = await fetch()
    if result is not None:
        if len(_search_cache) > 500:
            _search_cache.clear()
        _search_cache[key] = (time.monotonic(), result)
    return result


async def _search_classic(query: str, limit: int) -> list[dict] | None:
    params = {
        "search_terms": query, "search_simple": 1, "json": 1, "page_size": limit,
        "sort_by": "unique_scans_n", "fields": OFF_FIELDS,
    }
    for attempt in range(2):  # 503 от лимита OFF часто проходит со второй попытки
        try:
            async with httpx.AsyncClient(timeout=8.0, headers=HEADERS) as client:
                r = await client.get(OFF_SEARCH_URL, params=params)
            if r.status_code == 200:
                return list(r.json().get("products") or [])
            if r.status_code not in (429, 503) or attempt:
                return None
        except (httpx.HTTPError, ValueError):
            if attempt:
                return None
        await asyncio.sleep(1.0)
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


# --- Ранжирование по похожести (своё: у OFF нет поиска по началу слова и опечаткам) ---
def _token_score(qt: str, tokens: list[str]) -> float:
    best = 0.0
    for ct in tokens:
        if ct == qt:
            return 1.0
        if len(qt) >= 2 and ct.startswith(qt):
            best = max(best, 0.9)
        elif len(qt) >= 4 and len(ct) >= 4:
            # опечатка в слове целиком или в его начале («леванская», «левансх»)
            r = max(SequenceMatcher(None, qt, ct).ratio(), SequenceMatcher(None, qt, ct[: len(qt)]).ratio())
            if r >= 0.75:
                best = max(best, 0.8 * r)
    return best


def match_score(query: str, text: str) -> float:
    """0…1: насколько слова запроса похожи на слова названия и бренда."""
    words = normalize_query(query).split()
    tokens = normalize_query(text).split()
    if not words or not tokens:
        return 0.0
    return sum(_token_score(w, tokens) for w in words) / len(words)


def rank_products(products: list[dict], query: str, limit: int) -> list[dict]:
    """Без дублей по штрихкоду, лучшие совпадения первыми; при равенстве — исходный
    порядок (популярность в OFF). Слабые совпадения (< 0,5) — только если лучше нет."""
    seen, scored = set(), []
    for i, p in enumerate(products):
        code = str(p.get("code") or "") or f"#{i}"
        if code in seen:
            continue
        seen.add(code)
        name = p.get("product_name_ru") or p.get("product_name") or ""
        brands = p.get("brands") or ""
        scored.append((match_score(query, f"{name} {brands}"), i, p))
    scored.sort(key=lambda t: (-t[0], t[1]))
    good = [t for t in scored if t[0] >= 0.5]
    return [p for _, _, p in (good or scored)][:limit]


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

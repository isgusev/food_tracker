"""Кассовые чеки: импорт по QR и сопоставление строк чека со списком покупок.

Как это работает:
- QR чека (t=…&s=…&fn=…&i=…&fp=…) отправляем в code-qr.ru (app/services/receipt_client.py),
  он достаёт позиции из ФНС. Чеки доходят до ФНС с задержкой (минуты–часы), поэтому
  «ждём» (pending) — нормальное состояние: чек сохранён, клиент переспрашивает позже;
- для каждой строки чека предлагаем действие: list — отметить строку списка покупок
  купленной, extra — куплен продукт не из списка, skip — пропустить (не еда / не узнали).
  Кандидаты по порядку: (а) выученное по прошлым чекам соответствие (сначала того же
  магазина, потом любого), (б) неотмеченные строки активного списка, (в) справочник;
  нечто явно несъедобное (пакет, салфетки) из справочника не предлагаем;
- количество — в базовой единице продукта: из размера в названии («500г», «1,5л»,
  «10шт», последний размер — «62,5г*8пак 500г» → 500 г), весовой товар (дробное
  количество или «вес») — количество × 1000 г;
- применение чека — одной транзакцией через обычные «Куплено» / партии запасов
  (цена = сумма строки, дата покупки = дата чека) и запоминание соответствий.
"""
from __future__ import annotations


import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit

from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationError
from app.domain import UNIT_G, UNIT_ML, UNIT_PCS, base_to_grams, grams_to_base, quantize
from app.models.product import Product
from app.models.receipt import Receipt, ReceiptAlias
from app.models.stock import ShoppingLine
from app.repositories.receipt import ReceiptAliasRepository, ReceiptRepository
from app.repositories.stock import ShoppingListRepository, StockRepository
from app.schemas.receipt import (
    ApplyLine,
    ReceiptApply,
    ReceiptBrief,
    ReceiptItemOut,
    ReceiptOut,
    Suggestion,
)
from app.schemas.stock import LineCheck, LotAdd
from app.services import receipt_client
from app.services.barcode import _token_score, normalize_query
from app.services.stock import StockService, brand_of

ZERO = Decimal("0")
KG = Decimal("1000")
# Ниже этого сходства (0…1) не предлагаем ничего — пусть человек выберет сам
MATCH_THRESHOLD = 0.6
# Выученное соответствие: того же магазина — наверняка, другого — почти
ALIAS_SAME_STORE = 1.0
ALIAS_OTHER_STORE = 0.9


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v).replace(" ", "").replace(" ", "").replace(",", ".")) if v not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


# ===================================================== нормализация названий
# Сокращения со знаками («/», «-») — до разбиения на слова; порядок важен
_PHRASES: list[tuple[re.Pattern, str]] = [
    (re.compile(p), r) for p, r in (
        (r"т/бумага", "туалетная бумага"),
        (r"д/посуды|д/пос\b", "для посуды"),
        (r"д/", "для "),
        (r"с/к", "сырокопченая"),
        (r"в/к", "варено-копченая"),
        (r"с/м", "свежемороженые"),
        (r"ср-во", "средство"),
        # отметки об упаковке/обработке — для сопоставления бесполезны
        (r"\b(?:в/у|в/п|у/п|м/у|т/п|п/э|ж/б|ст/б|пл/б)(?![а-яa-z])", " "),
    )
]
# Сокращения слов в чеках (после нормализации; точка в конце уже убрана)
ABBREVIATIONS: dict[str, str] = {
    "мол": "молоко",
    "сгущ": "сгущенное",
    "кревет": "креветки",
    "говяд": "говядина",
    "свин": "свинина",
    "пит": "питьевое",
    "раст": "растительное",
    "подсолн": "подсолнечное",
    "слив": "сливочное",
    "майон": "майонез",
    "морож": "мороженое",
    "шок": "шоколад",
    "мин": "минеральная",
    "минер": "минеральная",
    "жев": "жевательная",
    "газ": "газированная",
    "негаз": "негазированная",
    "охл": "охлажденная",
    "зам": "замороженные",
    "конс": "консервированные",
    "пастер": "пастеризованное",
}
# Слова-пометки, которые ничего не говорят о товаре
_NOISE = {"бзмж", "мдж", "уп", "упак", "вес", "весовой", "весовые", "развес", "шт", "кг", "г", "гр", "л", "мл"}

_SIZE_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(кг|гр|г|мл|л|шт)(?![a-zа-я])")
_HAS_DIGIT = re.compile(r"\d")


def normalize_receipt_name(name: str) -> str:
    """Название строки чека в сравнимом виде: регистр, ё→е, пробелы, сокращения.

    «Молоко СВЕЖЕЕ ЗАВТРА у/п пит 3,2% 500г» → «молоко свежее завтра питьевое 3,2% 500г».
    Это же — ключ выученного соответствия (размер упаковки в нём остаётся).
    """
    text = (name or "").lower().replace("ё", "е")
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    words = [ABBREVIATIONS.get(w, w) for w in normalize_query(text).split()]
    return " ".join(words)


def match_text(norm_name: str) -> str:
    """Для сравнения с продуктами: без размеров упаковки, количеств и пометок."""
    text = _SIZE_RE.sub(" ", norm_name)
    return " ".join(
        w for w in text.split()
        if w not in _NOISE and not (_HAS_DIGIT.search(w) and "%" not in w)
    )


# ============================================================ размер упаковки
@dataclass(frozen=True)
class Pack:
    """Сколько товара в ОДНОЙ единице строки чека (unit: g | ml | pcs)."""

    amount: Decimal | None
    unit: str | None
    weighed: bool = False


def parse_pack(name: str, quantity: Decimal | float | int = 1) -> Pack:
    """«Молоко 500г» → 500 г; «62,5г*8пак 500г» → 500 г (последний размер);
    «Лимоны вес 1кг» × 0,416 → весовой: 1000 г на единицу (всего 416 г)."""
    norm = normalize_receipt_name(name)
    q = Decimal(str(quantity))
    sizes = list(_SIZE_RE.finditer(norm))
    fractional = q != q.to_integral_value()
    by_weight = bool(re.search(r"(?<![а-я])(?:вес|весовой|весовые|развес)(?![а-я])", norm))
    if sizes:
        value = Decimal(sizes[-1].group(1).replace(",", "."))
        unit = sizes[-1].group(2)
        if unit == "кг":
            amount, unit = value * KG, UNIT_G
        elif unit in ("г", "гр"):
            amount, unit = value, UNIT_G
        elif unit == "л":
            amount, unit = value * KG, UNIT_ML
        elif unit == "мл":
            amount, unit = value, UNIT_ML
        else:
            amount, unit = value, UNIT_PCS
    else:
        amount, unit = None, None
    # весовой товар: касса считает в килограммах, «1кг» в названии — цена за кг
    if fractional or (by_weight and (amount is None or (unit == UNIT_G and amount == KG))):
        return Pack(KG, UNIT_G, weighed=True)
    return Pack(amount, unit)


def to_base(amount: Decimal, unit: str, product: Product) -> Decimal | None:
    """Количество из чека (г/мл/шт) → базовая единица продукта (None — не перевести)."""
    base, piece = product.base_unit, product.piece_weight_g
    if unit in (UNIT_G, UNIT_ML):
        if base in (UNIT_G, UNIT_ML):
            return amount  # мл ≈ г, как и везде в учёте
        return grams_to_base(amount, base, piece) if piece else None
    if base == UNIT_PCS:
        return amount
    return base_to_grams(amount, UNIT_PCS, piece) if piece else None


def item_quantity(item: dict, product: Product, pack_amount: Decimal | None = None) -> Decimal | None:
    """Сколько куплено по строке чека в базовой единице продукта (None — не понять)."""
    q = Decimal(str(item.get("quantity") or 0))
    if q <= 0:
        return None
    if pack_amount:
        return quantize(q * Decimal(str(pack_amount)))
    pack = parse_pack(item.get("name") or "", q)
    if pack.amount is not None:
        per = to_base(pack.amount, pack.unit, product)
        if per:
            return quantize(q * per)
    if product.base_unit == UNIT_PCS and q == q.to_integral_value():
        return q
    packages = list(product.packages or [])
    if len(packages) == 1:  # упаковка у продукта одна — значит, она
        return quantize(q * Decimal(str(packages[0].amount)))
    return None


# ========================================================== «не еда»
_NONFOOD_WORDS = {"пакет", "пакеты", "пакет-майка", "майка"}
_NONFOOD_STEMS = (
    "салфет", "бумаг", "губк", "прокладк", "тампон", "подгуз", "средств", "порош",
    "мыло", "шампун", "зубн", "освеж", "фольг", "пленк", "батарейк", "сигарет",
    "зажигалк", "лампочк", "перчатк", "мешк", "кондиционер для белья",
)


def is_non_food(name: str) -> bool:
    """Пакет, салфетки, бытовая химия… (жевательная резинка — еда)."""
    norm = normalize_receipt_name(name)
    words = norm.split()
    if any(w in _NONFOOD_WORDS for w in words):
        return True
    return any(w.startswith(s) for w in words for s in _NONFOOD_STEMS if " " not in s) or any(
        s in norm for s in _NONFOOD_STEMS if " " in s
    )


# ============================================================ похожесть
def _word_score(word: str, tokens: list[str]) -> float:
    best = _token_score(word, tokens)
    if best < 0.85:
        # в чеках слова обрезают: «греч» → «греческий»
        for t in tokens:
            if len(t) >= 3 and word.startswith(t):
                best = max(best, 0.85)
    return best


def product_score(product: Product, text: str) -> float:
    """0…1: все ли слова названия продукта есть в строке чека. Бренд — лишь
    небольшая прибавка (в чеках его часто нет), чтобы различать равные."""
    tokens = text.split()
    words = normalize_query(product.name).split()
    if not words or not tokens:
        return 0.0
    score = sum(_word_score(w, tokens) for w in words) / len(words)
    brand = brand_of(product)
    if brand:
        bw = normalize_query(brand).split()
        if bw and sum(_word_score(w, tokens) for w in bw) / len(bw) >= 0.8:
            score = min(1.0, score + 0.05)
    return score


def _rank(product: Product, text: str) -> tuple[float, int]:
    # при равном сходстве — более подробное название («молоко 3,2%» точнее «молока»)
    return product_score(product, text), len(normalize_query(product.name).split())


def _search_patterns(text: str) -> set[str]:
    """Кусочки слов для предварительного отбора продуктов справочника в БД."""
    return {w[:5] for w in text.split() if len(w) >= 3 and not _HAS_DIGIT.search(w)}


# ============================================================ разбор ответа
def parse_qr(qr: str) -> dict[str, str]:
    """Поля QR чека (t, s, fn, i, fp, n) — из строки или из ссылки с ними."""
    raw = qr.strip()
    if "://" in raw:
        parts = urlsplit(raw)
        raw = parts.query or parts.fragment
    return {k: v[0] for k, v in parse_qs(raw).items() if v}


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y%m%dT%H%M", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _money(value) -> Decimal | None:
    v = _dec(value)
    return v.quantize(Decimal("0.01")) if v is not None else None


def normalize_items(raw_items) -> list[dict]:
    """Позиции чека в нашем виде: name, quantity, price, sum (числа JSON)."""
    out = []
    for it in raw_items or []:
        if not isinstance(it, dict):
            continue
        name = " ".join(str(it.get("name") or "").split())
        if not name:
            continue
        qty = _dec(it.get("quantity")) or Decimal("1")
        price = _dec(it.get("price")) or ZERO
        total = _dec(it.get("sum"))
        if total is None:
            total = price * qty
        out.append({
            "name": name,
            "quantity": float(round(qty, 3)),
            "price": float(round(price, 2)),
            "sum": float(round(total, 2)),
        })
    return out


# ================================================================== сервис
@dataclass
class _Pick:
    action: str
    source: str
    confidence: float
    product: Product | None = None
    line: ShoppingLine | None = None
    pack_amount: Decimal | None = None


class ReceiptService:
    def __init__(
        self,
        receipts: ReceiptRepository,
        aliases: ReceiptAliasRepository,
        lists: ShoppingListRepository,
        stock_repo: StockRepository,
        stock: StockService,
    ) -> None:
        self._receipts = receipts
        self._aliases = aliases
        self._lists = lists
        self._stock_repo = stock_repo
        self._stock = stock

    # ------------------------------------------------------------ загрузка
    async def create(self, household_id: int, user_id: int | None, qr: str) -> ReceiptOut:
        """Занести чек по QR (тот же QR в семье — тот же чек) и сразу спросить позиции."""
        qr = qr.strip()
        if not qr:
            raise ValidationError("Пустая строка QR")
        receipt = await self._receipts.by_qr(household_id, qr)
        if receipt is not None and receipt.status not in ("error",):
            if receipt.status == "pending":
                await self._refresh(receipt)
            return await self._out(receipt)
        fields = parse_qr(qr)
        receipt_hash = await receipt_client.add_qr(qr)
        if receipt is None:
            receipt = await self._receipts.create(Receipt(
                household_id=household_id, qr_raw=qr, status="pending", created_by_user_id=user_id,
                purchased_at=_parse_dt(fields.get("t")), total=_money(fields.get("s")),
            ))
        # ошибка в прошлый раз (ФНС ещё не знала чек) — пробуем заново
        receipt.provider_hash = receipt_hash
        receipt.status, receipt.error = "pending", None
        await self._receipts.flush()
        await self._refresh(receipt)
        return await self._out(receipt)

    async def get(self, household_id: int, receipt_id: int) -> ReceiptOut:
        """Чек; если ещё ждём ФНС — переспросить сервис."""
        receipt = await self._owned(household_id, receipt_id)
        if receipt.status == "pending":
            await self._refresh(receipt)
        return await self._out(receipt)

    async def recent(self, household_id: int) -> list[ReceiptBrief]:
        return [
            ReceiptBrief(
                id=r.id, status=r.status, store_name=r.store_name, purchased_at=r.purchased_at,
                total=r.total, items_count=len(r.items or []), created_at=r.created_at, applied_at=r.applied_at,
            )
            for r in await self._receipts.recent(household_id)
        ]

    async def _owned(self, household_id: int, receipt_id: int) -> Receipt:
        receipt = await self._receipts.get(receipt_id)
        if receipt is None or receipt.household_id != household_id:
            raise NotFoundError("Чек не найден")
        return receipt

    async def _refresh(self, receipt: Receipt) -> None:
        """Спросить сервис о чеке. Сеть недоступна — остаёмся «ждём», без ошибки."""
        if not receipt.provider_hash:
            return
        try:
            data = await receipt_client.info(receipt.provider_hash)
        except ServiceUnavailableError:
            return
        self._apply_info(receipt, data)
        await self._receipts.flush()

    @staticmethod
    def _apply_info(receipt: Receipt, data: dict) -> None:
        if not data.get("success"):
            receipt.status = "error"
            receipt.error = str(data.get("message") or "Чек не найден")[:500]
            return
        status = data.get("status")
        if status == "error":
            receipt.status = "error"
            receipt.error = str(data.get("error") or "Сервис не смог получить чек из ФНС")[:500]
            return
        if status != "done":  # wait — в очереди, process — проверяется
            receipt.status = "pending"
            return
        result = data.get("result") or {}
        receipt.store_name = (" ".join(str(result.get("user") or "").split()) or None)
        receipt.store_inn = (str(result.get("user_inn") or "").strip() or None)
        receipt.purchased_at = _parse_dt(data.get("t")) or receipt.purchased_at
        receipt.total = _money(data.get("s")) or receipt.total
        receipt.items = normalize_items(result.get("items"))
        receipt.status, receipt.error = "done", None

    # --------------------------------------------------------- подсказки
    async def suggest(self, receipt: Receipt) -> list[_Pick]:
        """Подсказка для каждой строки чека (порядок — как в чеке)."""
        items = receipt.items or []
        norms = [normalize_receipt_name(it["name"]) for it in items]
        texts = [match_text(n) for n in norms]
        picks: list[_Pick | None] = [None] * len(items)

        lst = await self._lists.active(receipt.household_id)
        open_lines = [ln for ln in (lst.lines if lst else []) if not ln.is_checked and ln.product is not None]
        used_lines: set[int] = set()

        def free_line_for(product: Product) -> ShoppingLine | None:
            for ln in open_lines:
                if ln.id not in used_lines and ln.product.search_name == product.search_name:
                    return ln
            return None

        # (а) выученное: сначала тот же магазин, потом любой (больше совпадений — раньше)
        aliases = await self._aliases.for_names(receipt.household_id, set(norms))
        for i, norm in enumerate(norms):
            mine = [a for a in aliases if a.norm_name == norm]
            if not mine:
                continue
            same = [a for a in mine if receipt.store_inn and a.store_inn == receipt.store_inn]
            alias = (same or mine)[0]
            product = await self._stock_repo.product(alias.product_id)
            if product is None:
                continue
            conf = ALIAS_SAME_STORE if same else ALIAS_OTHER_STORE
            line = free_line_for(product)
            if line is not None:
                used_lines.add(line.id)
                picks[i] = _Pick("list", "alias", conf, product, line, alias.pack_amount)
            else:
                picks[i] = _Pick("extra", "alias", conf, product, None, alias.pack_amount)

        # (б) строки списка: лучшие пары «строка чека — строка списка», каждая один раз
        pairs = []
        for i, text in enumerate(texts):
            if picks[i] is not None:
                continue
            for ln in open_lines:
                if ln.id in used_lines:
                    continue
                score, detail = _rank(ln.product, text)
                if score >= MATCH_THRESHOLD:
                    pairs.append((-score, -detail, i, ln.id, ln, score))
        pairs.sort(key=lambda p: p[:4])
        for _, _, i, line_id, ln, score in pairs:
            if picks[i] is None and line_id not in used_lines:
                used_lines.add(line_id)
                picks[i] = _Pick("list", "list", score, ln.product, ln)

        # (в) справочник — для еды, которой нет в списке
        for i, text in enumerate(texts):
            if picks[i] is not None:
                continue
            if is_non_food(items[i]["name"]):
                picks[i] = _Pick("skip", "none", 0.0)
                continue
            best: tuple[tuple[float, int], Product] | None = None
            for product in await self._receipts.catalog_candidates(_search_patterns(text)):
                rank = _rank(product, text)
                if best is None or rank > best[0]:
                    best = (rank, product)
            if best is not None and best[0][0] >= MATCH_THRESHOLD:
                picks[i] = _Pick("extra", "catalog", best[0][0], best[1])
            else:
                picks[i] = _Pick("skip", "none", 0.0)
        return picks  # type: ignore[return-value]

    @staticmethod
    def _line_default(line: ShoppingLine) -> Decimal | None:
        if line.package_amount and line.package_count:
            return Decimal(str(line.package_amount)) * line.package_count
        return Decimal(str(line.needed)) if line.needed else None

    def _suggestion(self, item: dict, pick: _Pick) -> Suggestion:
        product = pick.product
        qty = item_quantity(item, product, pick.pack_amount) if product is not None else None
        if qty is None and pick.line is not None:
            qty = self._line_default(pick.line)
        return Suggestion(
            action=pick.action,
            source=pick.source,
            confidence=round(pick.confidence, 2),
            shopping_line_id=pick.line.id if pick.line is not None else None,
            product_id=product.id if product is not None else None,
            product_name=product.name if product is not None else None,
            brand=brand_of(product),
            unit=product.base_unit if product is not None else None,
            quantity=qty,
        )

    async def _out(self, receipt: Receipt) -> ReceiptOut:
        items = receipt.items or []
        picks = await self.suggest(receipt) if receipt.status == "done" else [None] * len(items)
        return ReceiptOut(
            id=receipt.id, status=receipt.status, error=receipt.error, store_name=receipt.store_name,
            store_inn=receipt.store_inn, purchased_at=receipt.purchased_at, total=receipt.total,
            created_at=receipt.created_at, applied_at=receipt.applied_at,
            items=[
                ReceiptItemOut(
                    index=i, name=it["name"], quantity=_dec(it["quantity"]), price=_dec(it["price"]),
                    sum=_dec(it["sum"]), suggestion=self._suggestion(it, pick) if pick is not None else None,
                )
                for i, (it, pick) in enumerate(zip(items, picks))
            ],
        )

    # --------------------------------------------------------- применение
    async def apply(
        self, household_id: int, user_id: int | None, receipt_id: int, data: ReceiptApply, today: date
    ) -> ReceiptOut:
        """Разнести чек: list — «Куплено» строке списка, extra — партия в запасы
        (и строка «вне плана» в активном списке), skip — ничего. Цена партии — сумма
        строки чека, дата покупки — дата чека. Всё или ничего (одна транзакция)."""
        receipt = await self._owned(household_id, receipt_id)
        if receipt.status == "applied":
            raise ConflictError("Чек уже применён")
        if receipt.status == "pending":
            await self._refresh(receipt)
        if receipt.status == "pending":
            raise ValidationError("Чек ещё не пришёл из ФНС — попробуйте позже")
        if receipt.status != "done":
            raise ValidationError(f"Чек не загружен: {receipt.error or 'ошибка сервиса'}")
        items = receipt.items or []
        purchased_on = receipt.purchased_at.date() if receipt.purchased_at else today
        seen_items: set[int] = set()
        seen_lines: set[int] = set()
        for ln in data.lines:
            if ln.index >= len(items):
                raise ValidationError(f"В чеке нет строки №{ln.index + 1}")
            if ln.index in seen_items:
                raise ValidationError(f"Строка чека №{ln.index + 1} указана дважды")
            seen_items.add(ln.index)
            if ln.action == "skip":
                continue
            item = items[ln.index]
            price = ln.price if ln.price is not None else _money(item["sum"])
            if ln.action == "list":
                if ln.shopping_line_id is None:
                    raise ValidationError(f"«{item['name']}»: не выбрана строка списка покупок")
                if ln.shopping_line_id in seen_lines:
                    raise ValidationError("Одна строка списка покупок выбрана для нескольких строк чека")
                seen_lines.add(ln.shopping_line_id)
                product, qty = await self._apply_list(household_id, user_id, item, ln, price, purchased_on)
            else:
                product, qty = await self._apply_extra(household_id, user_id, item, ln, price, purchased_on, today)
            await self._learn(receipt, item, product, qty)
        receipt.status = "applied"
        receipt.applied_at = _now()
        await self._receipts.flush()
        return await self._out(receipt)

    async def _apply_list(
        self, household_id: int, user_id: int | None, item: dict, ln: ApplyLine, price, purchased_on: date
    ) -> tuple[Product, Decimal | None]:
        lst, line = await self._stock.get_owned_line(ln.shopping_line_id, household_id)
        if line.is_checked:
            raise ValidationError(f"«{line.product.name}» уже отмечено в списке купленным")
        product = line.product
        qty = ln.quantity or item_quantity(item, product)
        # обычное «Куплено»: партия с ценой; дата покупки — дата чека
        await self._stock.check(lst, line, LineCheck(quantity=qty, price=price), user_id, purchased_on)
        if qty is None and line.lot_id is not None:  # взяли количество по упаковкам строки
            lot = await self._stock_repo.get(line.lot_id)
            qty = Decimal(str(lot.quantity)) if lot is not None else None
        return product, qty

    async def _apply_extra(
        self, household_id: int, user_id: int | None, item: dict, ln: ApplyLine, price,
        purchased_on: date, today: date,
    ) -> tuple[Product, Decimal | None]:
        if ln.product_id is None:
            raise ValidationError(f"«{item['name']}»: не выбран продукт")
        product = await self._stock_repo.product(ln.product_id)
        if product is None:
            raise NotFoundError("Продукт не найден")
        qty = ln.quantity or item_quantity(item, product)
        if qty is None:
            raise ValidationError(f"«{item['name']}»: укажите, сколько куплено")
        settings = await self._stock_repo.settings(household_id, product.search_name)
        if settings is not None and settings.is_staple:
            return product, qty  # базовый товар: остаток не ведём, только запоминаем
        lst = await self._lists.active(household_id)
        if lst is not None:
            # видно в списке как покупка «вне плана», дальше — обычное «Куплено»
            await self._stock.add_extra(lst, product.id, qty)
            line = max(
                (x for x in lst.lines if x.is_extra and not x.is_checked and x.product_id == product.id),
                key=lambda x: x.id,
            )
            await self._stock.check(lst, line, LineCheck(quantity=qty, price=price), user_id, purchased_on)
        else:
            await self._stock.add_lot(
                household_id, user_id,
                LotAdd(product_id=product.id, quantity=qty, price=price, purchased_on=purchased_on),
                source="purchase", today=today,
            )
        return product, qty

    async def _learn(self, receipt: Receipt, item: dict, product: Product, qty: Decimal | None) -> None:
        """Запомнить «эта строка чека этого магазина = этот продукт, столько-то на штуку»."""
        norm = normalize_receipt_name(item["name"])[:255]
        alias = await self._aliases.find(receipt.household_id, receipt.store_inn, norm)
        if alias is None:
            alias = ReceiptAlias(household_id=receipt.household_id, store_inn=receipt.store_inn, norm_name=norm, hits=0)
            self._aliases.add(alias)
        count = Decimal(str(item.get("quantity") or 0))
        alias.product_id = product.id
        alias.pack_amount = quantize(qty / count) if qty and count > 0 else None
        alias.hits = (alias.hits or 0) + 1
        alias.updated_at = _now()
        await self._aliases.flush()

"""Импорт рецептов из YAML (docs/RECIPE_IMPORT.md).

Один и тот же вызов сначала делается «на сухую» (dry_run) — отчёт: что создастся, что обновится, какие ингредиенты
не сопоставились. Пользователь выбирает продукты для несопоставленных (choices: ключ ингредиента → variant_id или
null — пропустить) и отмечает, какие уже существующие рецепты обновить (update), затем тот же файл — без dry_run.

Сопоставление — со всем справочником: точное название продукта или товара (без регистра, «ё», знаков) → он сам
(бренд из файла — среди них; без бренда — «Без бренда», иначе первый); иначе нечётко по словам (числа должны
совпадать: «Творог 5%» ≠ «Творог 9%»). Один явный лидер — подставляется «на проверку» (fuzzy), несколько похожих
(ambiguous) или ничего (missing) — рецепты с ним ждут выбора. Молча продукты не создаются: новый продукт
пользователь заводит в окне импорта обычным поиском (Open Food Facts / вручную) и выбирает его.
"""
from __future__ import annotations


import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

import yaml
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import DomainError, ValidationError
from app.domain import ZERO, quantize
from app.models.product import Product, ProductVariant
from app.models.recipe import RecipeCategory
from app.repositories.product import ProductRepository
from app.repositories.recipe import RecipeCategoryRepository, RecipeRepository
from app.schemas.common import meal_list
from app.schemas.recipe import IngredientLine, RecipeCreate, RecipeUpdate
from app.schemas.recipe_import import (
    ImportCandidate,
    ImportIngredient,
    ImportRecipeResult,
    RecipeImportIn,
    RecipeImportReport,
)
from app.services.barcode import normalize_query
from app.services.naming import brand_of
from app.services.recipe import RecipeService

MAX_RECIPES = 500
UNITS = {"г": "g", "гр": "g", "g": "g", "мл": "ml", "ml": "ml", "шт": "pcs", "pcs": "pcs"}
RECIPE_KEYS = {
    "name", "category", "servings", "cooked_weight", "time", "effort", "meal_types", "keeps_days", "freezable",
    "allow_half", "in_rotation", "ingredients", "steps", "source", "notes",
}
INGREDIENT_KEYS = {"product", "brand", "exact", "amount", "unit", "grams", "to_taste"}
MATCH_MIN = 0.6         # ниже — не кандидат
SURE = 0.85             # нечёткий лидер с отрывом — подставляется «на проверку»
GAP = 0.15
_NUM = re.compile(r"\d+(?:\.\d+)?")


# ============================================================ нормализация и похожесть
def norm(text) -> str:
    """Нижний регистр, ё→е, без знаков; «3,2%» → «3.2%»."""
    return normalize_query(str(text or "")).replace(",", ".")


def ingredient_key(product: str, brand: str = "") -> str:
    return f"{norm(product)}|{norm(brand)}"


def _words(n: str) -> list[str]:
    return [w for w in n.split() if not any(ch.isdigit() for ch in w) and w != "%"]


def _word_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    short = min(len(a), len(b))
    common = 0
    while common < short and a[common] == b[common]:
        common += 1
    if short >= 4 and common >= max(3, short - 2):     # окончания: «яйцо» ~ «яйца», «куриное» ~ «куриные»
        return 0.9
    if short >= 3 and (a.startswith(b) or b.startswith(a)):
        return 0.8
    if short >= 4:
        r = SequenceMatcher(None, a, b).ratio()
        if r >= 0.8:
            return 0.7 * r
    return 0.0


def similarity(query: str, name: str) -> float:
    """0…1: насколько название из справочника похоже на название из файла (оба после norm).
    Числа (жирность, сорт) обязаны совпадать; лишние слова в справочнике немного штрафуются."""
    if query == name:
        return 1.0
    if sorted(_NUM.findall(query)) != sorted(_NUM.findall(name)):
        return 0.0
    q, p = _words(query), _words(name)
    if not q or not p:
        return 0.0
    total = sum(max(_word_sim(w, t) for t in p) for w in q)
    extra = max(0, len(p) - len(q))
    return total / (len(q) + 0.5 * extra)


# ============================================================ справочник
@dataclass
class _Prod:
    product: Product
    variant: ProductVariant
    name: str      # norm(product.name)
    item: str      # norm(item.name)
    brand: str     # norm(бренд), «Без бренда» — ""


def _active_variant(product: Product) -> ProductVariant | None:
    brand = (brand_of(product) or "").lower()
    makers = sorted(product.manufacturers, key=lambda m: ((m.name or "").lower() != brand, m.id))
    for m in makers:
        for v in m.variants:
            if v.is_active:
                return v
    return None


def _candidate(p: _Prod, score: float) -> ImportCandidate:
    return ImportCandidate(
        variant_id=p.variant.id, product_id=p.product.id, name=p.product.name, brand=brand_of(p.product) or "",
        calories=Decimal(str(p.variant.calories)), kbju_missing=bool(p.product.kbju_missing), score=round(score, 2),
    )


def _rep(prods: list[_Prod], brand: str) -> _Prod:
    """Кто представляет товар: продукт нужного бренда → «Без бренда» → самый старый."""
    return min(prods, key=lambda p: (not (brand and p.brand == brand), p.brand != "", p.product.id))


def match(catalog: list[_Prod], product: str, brand: str, exact: bool) -> tuple[str, _Prod | None, list[tuple[float, _Prod]]]:
    """(статус, подставленный продукт, кандидаты по товарам — лучшие первыми)."""
    q, b = norm(product), norm(brand)
    scored = []
    for p in catalog:
        s = max(similarity(q, p.name), similarity(q, p.item) if p.item else 0.0)
        if s >= MATCH_MIN:
            scored.append((s, p))
    by_item: dict[str, list[tuple[float, _Prod]]] = {}
    for s, p in scored:
        by_item.setdefault(p.product.item_key or f"#{p.product.id}", []).append((s, p))
    reps = []
    for rows in by_item.values():
        best = max(s for s, _ in rows)
        reps.append((best, _rep([p for s, p in rows if s == best], b)))
    reps.sort(key=lambda x: (-x[0], x[1].product.id))
    top = reps[:6]

    sure = [p for s, p in scored if s >= 0.999]
    if sure:
        if b:
            same = [p for p in sure if p.brand == b]
            if same:
                return "matched", _rep(same, b), top
            # такого бренда нет: «именно этот» — пусть выберут; иначе подойдёт и другой бренд товара
            return ("ambiguous", None, top) if exact else ("fuzzy", _rep(sure, b), top)
        return "matched", _rep(sure, b), top
    if top and top[0][0] >= SURE and (len(top) == 1 or top[1][0] <= top[0][0] - GAP):
        return "fuzzy", top[0][1], top
    return ("ambiguous" if top else "missing"), None, top


# ============================================================ разбор файла
@dataclass
class _Ing:
    product: str
    brand: str
    exact: bool
    amount: Decimal
    unit: str          # g | ml | pcs
    grams: Decimal | None
    key: str


@dataclass
class _Rec:
    number: int
    raw_name: str = ""
    name: str = ""
    category: str = ""
    servings: int | None = None
    cooked_weight: Decimal | None = None
    time: int | None = None
    effort: str = "easy"
    meal_types: list[str] | None = None
    keeps_days: int = 2
    freezable: bool = False
    allow_half: bool = False
    in_rotation: bool = True
    steps: str = ""
    source: str = ""
    notes: str = ""
    ings: list[_Ing] = field(default_factory=list)
    to_taste: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def instructions(self) -> str | None:
        parts = [self.steps.strip()]
        if self.to_taste:
            parts.append("По вкусу: " + ", ".join(self.to_taste) + ".")
        if self.source.strip():
            parts.append(f"Источник: {self.source.strip()}")
        parts.append(self.notes.strip())
        text = "\n\n".join(p for p in parts if p)
        return text or None


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _number(v) -> Decimal | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _int(rec: _Rec, data: dict, key: str, lo: int, hi: int, *, required=False, default=None):
    if key not in data or data[key] is None:
        if required:
            rec.errors.append(f"нет поля {key}")
        return default
    d = _number(data[key])
    if d is None or d != d.to_integral_value() or not lo <= d <= hi:
        rec.errors.append(f"{key}: нужно целое число от {lo} до {hi}")
        return default
    return int(d)


def _bool(rec: _Rec, data: dict, key: str, default: bool) -> bool:
    v = data.get(key)
    if v is None:
        return default
    if not isinstance(v, bool):
        rec.errors.append(f"{key}: нужно true или false")
        return default
    return v


def _parse_ingredient(rec: _Rec, j: int, raw) -> None:
    where = f"ингредиент {j}"
    if not isinstance(raw, dict):
        rec.errors.append(f"{where}: ожидается {{product: …, amount: …, unit: …}}")
        return
    product = _text(raw.get("product"))
    if not product:
        rec.errors.append(f"{where}: нет поля product")
        return
    where = f"ингредиент {j} «{product}»"
    unknown = sorted(set(map(str, raw)) - INGREDIENT_KEYS)
    if unknown:
        rec.warnings.append(f"{where}: неизвестные поля {', '.join(unknown)} — пропущены")
    if raw.get("to_taste") is True:
        rec.to_taste.append(product)
        return
    amount = _number(raw.get("amount"))
    if amount is None or amount <= 0:
        rec.errors.append(f"{where}: amount — положительное число (или to_taste: true)")
        return
    unit = UNITS.get(_text(raw.get("unit")).lower().rstrip("."))
    if unit is None:
        rec.errors.append(f"{where}: unit — г, мл или шт (ложки и стаканы переведите в г или мл)")
        return
    grams = None
    if raw.get("grams") is not None:
        grams = _number(raw.get("grams"))
        if grams is None or grams <= 0:
            rec.errors.append(f"{where}: grams — положительное число")
            return
    brand = _text(raw.get("brand"))
    exact = raw.get("exact") is True
    if exact and not brand:
        rec.warnings.append(f"{where}: exact без brand не действует")
        exact = False
    rec.ings.append(_Ing(product, brand, exact, amount, unit, grams, ingredient_key(product, brand)))


def parse_recipe(number: int, raw) -> _Rec:
    rec = _Rec(number)
    if not isinstance(raw, dict):
        rec.errors.append("ожидается рецепт: name, category, servings, ingredients…")
        return rec
    rec.raw_name = rec.name = _text(raw.get("name"))[:255]
    if not rec.name:
        rec.errors.append("нет поля name")
    rec.category = _text(raw.get("category"))
    if not rec.category:
        rec.errors.append("нет поля category")
    elif len(rec.category) > 100:
        rec.errors.append("category длиннее 100 символов")
    unknown = sorted(set(map(str, raw)) - RECIPE_KEYS)
    if unknown:
        rec.warnings.append(f"неизвестные поля {', '.join(unknown)} — пропущены")

    rec.servings = _int(rec, raw, "servings", 1, 100, required=True)
    if raw.get("cooked_weight") is not None:
        cw = _number(raw["cooked_weight"])
        if cw is None or not ZERO < cw <= Decimal("99999.9"):
            rec.errors.append("cooked_weight: вес готового в граммах, больше 0")
        else:
            rec.cooked_weight = quantize(cw)
    rec.time = _int(rec, raw, "time", 0, 10000)
    rec.keeps_days = _int(rec, raw, "keeps_days", 1, 14, default=2)
    effort = _text(raw.get("effort")).lower() or "easy"
    if effort not in ("easy", "special"):
        rec.errors.append("effort: easy или special")
    else:
        rec.effort = effort
    meals = raw.get("meal_types")
    if meals is not None:
        try:
            rec.meal_types = meal_list([str(m) for m in meals] if isinstance(meals, list) else [str(meals)], empty_is_any=True)
        except ValueError:
            rec.errors.append("meal_types: только breakfast, lunch, dinner, snack")
    rec.freezable = _bool(rec, raw, "freezable", False)
    rec.allow_half = _bool(rec, raw, "allow_half", False)
    rec.in_rotation = _bool(rec, raw, "in_rotation", True)
    rec.steps, rec.source, rec.notes = _text(raw.get("steps")), _text(raw.get("source")), _text(raw.get("notes"))

    ings = raw.get("ingredients")
    if not isinstance(ings, list) or not ings:
        rec.errors.append("нет списка ingredients")
    else:
        for j, ing in enumerate(ings, 1):
            _parse_ingredient(rec, j, ing)
        if not rec.errors and not rec.ings:
            rec.errors.append("в составе только «по вкусу» — нужен хоть один ингредиент с количеством")
    return rec


def load_file(content: str) -> list:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (строка {mark.line + 1})" if mark is not None else ""
        raise ValidationError(f"Файл не читается как YAML{where}: {getattr(e, 'problem', None) or e}")
    if isinstance(data, dict) and isinstance(data.get("recipes"), list):
        data = data["recipes"]
    if not isinstance(data, list) or not data:
        raise ValidationError("В корне файла должен быть список рецептов (каждый начинается с «- name: …»)")
    if len(data) > MAX_RECIPES:
        raise ValidationError(f"Слишком много рецептов в одном файле: {len(data)} (не больше {MAX_RECIPES})")
    return data


# ============================================================ сервис
@dataclass
class _Resolved:
    status: str
    pick: _Prod | None
    top: list[tuple[float, _Prod]]


class RecipeImportService:
    def __init__(
        self,
        recipes_svc: RecipeService,
        recipes: RecipeRepository,
        categories: RecipeCategoryRepository,
        products: ProductRepository,
    ) -> None:
        self._svc = recipes_svc
        self._recipes = recipes
        self._categories = categories
        self._products = products

    async def _catalog(self) -> list[_Prod]:
        out = []
        for p in await self._products.list_full(limit=100_000):
            v = _active_variant(p)
            if v is not None:
                out.append(_Prod(p, v, norm(p.name), norm(p.item.name) if p.item else "", norm(brand_of(p) or "")))
        return out

    async def run(self, household_id: int, user_id: int, data: RecipeImportIn) -> RecipeImportReport:
        recs = [parse_recipe(i, raw) for i, raw in enumerate(load_file(data.content), 1)]

        # одинаковые названия в файле — второй с ошибкой
        seen: dict[str, int] = {}
        for r in recs:
            if not r.name:
                continue
            k = norm(r.name)
            if k in seen:
                r.errors.append(f"в файле уже есть рецепт с этим названием (№{seen[k]})")
            else:
                seen[k] = r.number

        # сопоставление: каждый «продукт + бренд» — один раз на весь файл
        catalog = await self._catalog()
        by_variant = {p.variant.id: p for p in catalog}
        resolved: dict[str, _Resolved] = {}
        uses: dict[str, list[int]] = {}
        for r in recs:
            if r.errors:
                continue
            for ing in r.ings:
                uses.setdefault(ing.key, [])
                if r.number not in uses[ing.key]:
                    uses[ing.key].append(r.number)
                if ing.key in resolved:
                    continue
                status, pick, top = match(catalog, ing.product, ing.brand, ing.exact)
                if ing.key in data.choices:
                    chosen = data.choices[ing.key]
                    if chosen is None:
                        status, pick = "skipped", None
                    elif chosen in by_variant:
                        status, pick = "chosen", by_variant[chosen]
                resolved[ing.key] = _Resolved(status, pick, top)

        existing = {norm(name): rid for rid, name in await self._recipes.names(household_id)}
        categories = {c.search_name: c for c in await self._svc.list_categories()}
        results: list[ImportRecipeResult] = []
        plans: list[tuple[_Rec, ImportRecipeResult, list[IngredientLine]]] = []
        for r in recs:
            res = ImportRecipeResult(number=r.number, name=r.name or f"Рецепт №{r.number}", status="error",
                                     category=r.category, servings=r.servings, warnings=list(r.warnings))
            results.append(res)
            if r.errors:
                res.errors = r.errors
                continue
            res.new_category = r.category.lower() not in categories
            lines, calories, waiting = self._lines(r, resolved, res)
            if res.errors:
                res.errors += waiting
                continue
            if waiting:
                res.errors, res.status = waiting, "waiting"
                continue
            if not lines:
                res.errors.append("все ингредиенты пропущены — нечего сохранять")
                continue
            raw_total = sum((ln.weight_g for ln in lines), ZERO)
            res.cooked_weight = r.cooked_weight or quantize(raw_total)
            if res.cooked_weight > Decimal("99999.9"):
                res.errors.append("выход больше 99 999 г — укажите cooked_weight")
                continue
            res.calories_per_100g = quantize(calories * 100 / res.cooked_weight)
            res.ingredients = len(lines)
            rid = existing.get(norm(r.name))
            if rid is None:
                res.status = "create"
            elif r.number in data.update:
                res.status, res.recipe_id = "update", rid
            else:
                res.status, res.recipe_id = "exists", rid
                res.warnings.append("рецепт с таким названием уже есть — пропустим (или отметьте «обновить»)")
            plans.append((r, res, lines))

        report = RecipeImportReport(dry_run=data.dry_run, recipes=results, ingredients=[
            ImportIngredient(
                key=k, product=ing.product, brand=ing.brand, status=rv.status, recipes=uses[k],
                pick=_candidate(rv.pick, 1.0) if rv.pick else None,
                candidates=[_candidate(p, s) for s, p in rv.top],
            )
            for k, rv, ing in self._unique(recs, resolved)
        ])
        if data.dry_run:
            return report

        for r, res, lines in plans:
            if res.status == "exists":
                res.status = "skipped"
                continue
            try:
                category = await self._category(categories, r.category)
                fields = dict(
                    name=r.name, recipe_category_id=category.id, cooking_time_minutes=r.time,
                    instructions=r.instructions(), default_servings=r.servings, allow_half=r.allow_half,
                    estimated_cooked_weight=res.cooked_weight, ingredients=lines, in_rotation=r.in_rotation,
                    effort=r.effort, meal_types=r.meal_types, keeps_days=r.keeps_days, is_freezable=r.freezable,
                )
                if res.status == "update":
                    recipe = await self._svc.update_recipe(res.recipe_id, household_id, RecipeUpdate(**fields))
                    res.status = "updated"
                    report.updated += 1
                else:
                    recipe = await self._svc.create_recipe(
                        household_id, user_id, RecipeCreate(**fields, created_by_user="import"))
                    res.status = "created"
                    report.created += 1
                res.recipe_id = recipe.id
            except (DomainError, PydanticValidationError) as e:
                res.status = "error"
                res.errors.append(str(e) if isinstance(e, DomainError) else "не прошёл проверку: " + "; ".join(
                    err["msg"] for err in e.errors()))
        return report

    @staticmethod
    def _unique(recs: list[_Rec], resolved: dict[str, _Resolved]):
        done = set()
        for r in recs:
            for ing in r.ings:
                if ing.key in resolved and ing.key not in done:
                    done.add(ing.key)
                    yield ing.key, resolved[ing.key], ing

    @staticmethod
    def _lines(
        r: _Rec, resolved: dict[str, _Resolved], res: ImportRecipeResult
    ) -> tuple[list[IngredientLine], Decimal, list[str]]:
        """Строки состава (одинаковые продукты сложены), сумма ккал и что ждёт пользователя (выбор продукта,
        КБЖУ); ошибки файла — в res.errors, замечания — в res.warnings."""
        weights: dict[tuple[int, bool], Decimal] = {}
        calories = ZERO
        waiting, no_kbju = [], []
        for ing in r.ings:
            rv = resolved[ing.key]
            if rv.status == "skipped":
                res.warnings.append(f"«{ing.product}» пропущен")
                continue
            if rv.pick is None:
                waiting.append(ing.product)
                continue
            p = rv.pick
            if p.product.kbju_missing:
                no_kbju.append(p.product.name)
                continue
            if ing.unit == "g":
                grams = ing.amount
            elif ing.grams is not None:
                grams = ing.grams
            elif ing.unit == "ml":
                grams = ing.amount
                res.warnings.append(f"«{ing.product}»: {ing.amount} мл без grams — считаю 1 мл = 1 г")
            elif p.product.piece_weight_g:
                grams = ing.amount * Decimal(str(p.product.piece_weight_g))
                res.warnings.append(f"«{ing.product}»: вес штуки из справочника — {p.product.piece_weight_g} г")
            else:
                res.errors.append(f"«{ing.product}»: укажите grams — сколько весят {ing.amount} шт")
                continue
            grams = quantize(grams)
            if grams <= 0:
                res.errors.append(f"«{ing.product}»: вес меньше 0,1 г")
                continue
            k = (p.variant.id, ing.exact and rv.status in ("matched", "chosen"))
            weights[k] = weights.get(k, ZERO) + grams
            calories += Decimal(str(p.variant.calories)) * grams / 100
        wait = []
        if waiting:
            wait.append("выберите продукт: " + ", ".join(dict.fromkeys(waiting)))
        if no_kbju:
            wait.append("нет КБЖУ у продукта: " + ", ".join(dict.fromkeys(no_kbju)) + " — внесите цифры")
        lines = [IngredientLine(variant_id=vid, weight_g=w, exact=ex) for (vid, ex), w in weights.items()]
        return lines, calories, wait

    async def _category(self, cache: dict[str, RecipeCategory], name: str) -> RecipeCategory:
        key = name.strip().lower()
        if key not in cache:
            cache[key] = await self._svc.create_category(name)
        return cache[key]

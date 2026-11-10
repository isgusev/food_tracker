"""Товары — базовые наименования без бренда («Кефир 3,2%»): список, предложения
объединить похожие, объединение, переименование, перенос продукта в другой товар.

Объединение = перепривязка продуктов к одному товару: партии, «базовые»,
цены и покупки следуют за продуктами сами (всё считается по Product.item_key).
Справочник общий для всех семей — настройки товара в семьях сливаются.
"""
from __future__ import annotations


import re

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.product import Item, Product
from app.repositories.item import ItemRepository
from app.services.barcode import match_score, normalize_query

# слова, не меняющие сути товара
_NOISE = {"в", "с", "и", "для", "из", "на", "по", "без", "шт", "уп", "упак", "упаковка"}
_SIZE = re.compile(r"^\d+(?:[.,]\d+)?(?:г|гр|кг|мл|л|шт)$")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def core_tokens(name: str, brands: set[str]) -> tuple[str, ...]:
    """Суть названия: без брендов, размеров упаковки, мусорных слов; «3,2» = «3.2»."""
    text = normalize_query(name).replace(",", ".")
    words = []
    brand_words = {w for b in brands for w in normalize_query(b).split()}
    for w in text.split():
        w = w.strip(".")
        if not w or w in _NOISE or w in brand_words or _SIZE.match(w):
            continue
        words.append(w)
    return tuple(sorted(words))


def _numbers(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(n for t in tokens for n in _NUM.findall(t)))


def suggest_groups(items: list[Item], threshold: float = 0.85) -> list[list[Item]]:
    """Группы похожих товаров (2+): одинаковая суть или почти одинаковая при тех же числах."""
    nodes: list[tuple[Item, tuple[str, ...]]] = []
    for it in items:
        brands = {p.brand.name for p in it.products if p.brand is not None}
        toks = core_tokens(it.name, brands)
        if toks:
            nodes.append((it, toks))
    parent = list(range(len(nodes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i][1], nodes[j][1]
            if a == b:
                parent[find(j)] = find(i)
                continue
            if _numbers(a) != _numbers(b):
                continue  # «кефир 2.5» и «кефир 3.2» — разные товары
            ta, tb = " ".join(a), " ".join(b)
            if min(match_score(ta, tb), match_score(tb, ta)) >= threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[Item]] = {}
    for i, (it, _) in enumerate(nodes):
        groups.setdefault(find(i), []).append(it)
    return [g for g in groups.values() if len(g) > 1]


def suggested_name(group: list[Item]) -> str:
    """Название для объединённого товара: самое короткое из названий без брендов."""
    best = None
    for it in group:
        brands = {normalize_query(p.brand.name) for p in it.products if p.brand is not None}
        words = [w for w in it.name.split() if normalize_query(w) not in {x for b in brands for x in b.split()}]
        cand = " ".join(words).strip() or it.name
        if best is None or len(cand) < len(best):
            best = cand
    return best[:1].upper() + best[1:] if best else group[0].name


class ItemService:
    def __init__(self, items: ItemRepository) -> None:
        self._items = items

    async def all(self) -> list[Item]:
        return [i for i in await self._items.all_with_products() if i.products]

    async def get(self, key: str) -> Item:
        """Товар с продуктами, брендами и упаковками (для ответа API)."""
        item = await self._items.get_full(key)
        if item is None:
            raise NotFoundError("Товар не найден")
        return item

    async def suggestions(self) -> list[tuple[str, list[Item]]]:
        return [(suggested_name(g), g) for g in suggest_groups(await self.all())]

    async def rename(self, key: str, name: str) -> Item:
        item = await self.get(key)
        item.name = name.strip()
        await self._items.flush()
        return item

    async def merge(self, keys: list[str], name: str | None) -> Item:
        """Слить товары в один: первый ключ — целевой. Единицы г и мл совместимы (1 мл = 1 г);
        штуки с граммами не сливаем — у них разный учёт."""
        keys = list(dict.fromkeys(keys))
        if len(keys) < 2:
            raise ValidationError("Выберите хотя бы два товара")
        items = [await self.get(k) for k in keys]
        target = items[0]
        products = await self._items.products_of(keys)
        tgt_products = [p for p in products if p.item_key == target.key]
        unit = tgt_products[0].base_unit if tgt_products else products[0].base_unit
        if any((p.base_unit == "pcs") != (unit == "pcs") for p in products):
            raise ConflictError("Нельзя объединить штучный товар с весовым — у них разный учёт запасов")
        if unit == "pcs" and len({p.piece_weight_g for p in products}) > 1:
            raise ConflictError("У штучных товаров разный вес штуки — выровняйте его в карточке продукта")
        for p in products:
            p.item_key = target.key
            p.base_unit = unit   # г ↔ мл — 1:1, упаковки и партии не пересчитываются
        await self._items.flush()
        await self._merge_settings(target.key, keys[1:])
        for it in items[1:]:
            await self._items.delete(it)
        if name and name.strip():
            target.name = name.strip()
        await self._items.flush()
        return target

    async def _merge_settings(self, target: str, others: list[str]) -> None:
        """«Базовый / заканчивается / учёт сбился» каждой семьи — в целевой товар (по «или»)."""
        by_household: dict[int, list] = {}
        for r in await self._items.settings_of([target, *others]):
            by_household.setdefault(r.household_id, []).append(r)
        for group in by_household.values():
            keep = next((r for r in group if r.item_key == target), None)
            rest = [r for r in group if r is not keep]
            if keep is None:
                keep = rest.pop(0)
                await self._items.rekey_setting(keep, target)
            for r in rest:
                keep.is_staple = keep.is_staple or r.is_staple
                keep.is_low = keep.is_low or r.is_low
                keep.needs_check = keep.needs_check or r.needs_check
                await self._items.delete(r)

    async def move_product(self, product: Product, item_key: str | None, new_name: str | None) -> Item:
        """Перенести продукт в другой товар или выделить в новый."""
        old_key = product.item_key
        if item_key:
            target = await self.get(item_key)
        else:
            name = (new_name or "").strip()
            if not name:
                raise ValidationError("Укажите товар или название нового товара")
            key = normalize_query(name)
            target = await self._items.get_by_key(key)
            if target is None:
                target = Item(key=key, name=name)
                self._items.add(target)
                await self._items.flush()
        if target.key == old_key:
            return target
        siblings = await self._items.products_of([target.key])
        if siblings and (siblings[0].base_unit == "pcs") != (product.base_unit == "pcs"):
            raise ConflictError("Нельзя перенести: у товара другой учёт (штуки против граммов)")
        if siblings:
            product.base_unit = siblings[0].base_unit
        product.item_key = target.key
        await self._items.flush()
        # в старом товаре продуктов не осталось — он не нужен, его настройки — за продуктом
        if not await self._items.has_products(old_key):
            await self._merge_settings(target.key, [old_key])
            old = await self._items.get_by_key(old_key)
            if old is not None:
                await self._items.delete(old)
            await self._items.flush()
        return target

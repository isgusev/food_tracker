"""Запасы семьи: партии, расход и отмены, пачки «Честного знака», списание, инвентаризация, настройки товара.

Правила:
- запасы сверяются по ТОВАРУ (продукт без бренда, ключ — Product.item_key); партия помнит
  конкретный продукт, бренд и цену;
- расход: готовка списывает фактический состав кастрюли, «съел» готовый продукт — порцию;
  порядок партий: тот же бренд → тот же продукт → непросроченные с ближайшим сроком → самые старые;
- не хватило — списываем что есть, остаток записываем «недостачей» (движение без партии)
  и помечаем товар «учёт сбился», без ошибки;
- «базовые» товары (соль, масло) не учитываются вовсе;
- каждое изменение — движение; отмена (удалили кастрюлю, сняли «съел») возвращает ровно то,
  что списали, в те же партии.

Список покупок — app/services/shopping.py, «обычно берём» и снеки — app/services/regular.py.
"""
from __future__ import annotations


from datetime import date
from decimal import Decimal

from app.core import clock
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain import UNITS, dec, grams_to_base, quantize
from app.models.plan import MealItem, MealPortion
from app.models.product import Product
from app.models.recipe import RecipeCookingLog
from app.models.stock import StockLot, StockMark, StockMovement
from app.repositories.stock import StockRepository
from app.services.marking import MarkInfo, parse_mark
from app.services.naming import brand_of
from app.schemas.stock import (
    ItemFlags,
    LotAdd,
    LotResponse,
    MarkParsed,
    MovementResponse,
    PackIn,
    PacksAdd,
    PacksSplit,
    StockItem,
)

ZERO = Decimal("0")
FAR = date(9999, 12, 31)

_d = dec
_now = clock.utc_now


class StockService:
    def __init__(self, stock: StockRepository) -> None:
        self._stock = stock

    # ================================================================= расход
    async def _consume(
        self,
        household_id: int,
        product: Product,
        qty: Decimal,
        reason: str,
        *,
        today: date,
        variant_id: int | None = None,
        pot_id: int | None = None,
        portion_id: int | None = None,
        user_id: int | None = None,
        note: str | None = None,
        record_shortfall: bool = True,
    ) -> Decimal:
        """Списать qty (базовая единица) товара по партиям. Вернёт недостачу."""
        # остатки хранятся с точностью 0,1 — округляем ДО сравнения, иначе
        # 100 г / 60 г = 1,666… шт даёт ложную «недостачу» в сотые доли
        qty = quantize(qty)
        if qty <= 0:
            return ZERO
        key = product.item_key
        settings = await self._stock.settings(household_id, key)
        if settings is not None and settings.is_staple:
            return ZERO  # базовые продукты не учитываем
        lots = await self._stock.open_lots_for_key(household_id, key)
        lots.sort(key=lambda lot: (
            lot.variant_id != variant_id if variant_id else False,
            lot.product_id != product.id,
            bool(lot.expires_on and lot.expires_on < today),   # непросроченные — раньше
            lot.expires_on or FAR,
            lot.id,
        ))
        left = qty
        for lot in lots:
            if left <= 0:
                break
            take = min(_d(lot.remaining), left)
            lot.remaining = _d(lot.remaining) - take
            left -= take
            self._stock.add_movement(StockMovement(
                household_id=household_id, product_id=lot.product_id, lot_id=lot.id, delta=-take,
                reason=reason, pot_id=pot_id, portion_id=portion_id, created_by_user_id=user_id, note=note,
            ))
        if left >= Decimal("0.1") and record_shortfall:
            self._stock.add_movement(StockMovement(
                household_id=household_id, product_id=product.id, lot_id=None, delta=-left,
                reason=reason, pot_id=pot_id, portion_id=portion_id, created_by_user_id=user_id,
                note="недостача: в запасах не числилось",
            ))
            (await self._stock.get_or_create_settings(household_id, key)).needs_check = True
        await self._stock.flush()
        return left

    async def revert(self, *, pot_id: int | None = None, portion_id: int | None = None) -> None:
        """Отменить списания кастрюли/порции: вернуть в те же партии."""
        for m in await self._stock.movements(pot_id=pot_id, portion_id=portion_id):
            if m.lot is not None:
                m.lot.remaining = _d(m.lot.remaining) - _d(m.delta)
            await self._stock.delete_obj(m)
        await self._stock.flush()

    async def consume_pot(self, pot: RecipeCookingLog, user_id: int | None, today: date) -> None:
        """Готовка: фактический состав кастрюли уходит из запасов."""
        for ing in pot.actual_ingredients:
            product = await self._stock.product_for_variant(ing.variant_id)
            if product is None:
                continue
            qty = grams_to_base(_d(ing.weight_g), product.base_unit, product.piece_weight_g)
            await self._consume(
                pot.household_id, product, qty, "cook",
                today=today, variant_id=ing.variant_id, pot_id=pot.id, user_id=user_id,
            )

    async def adjust_pot(
        self,
        pot: RecipeCookingLog,
        old_grams: dict[int, Decimal],
        new_grams: dict[int, Decimal],
        user_id: int | None,
        today: date,
    ) -> None:
        """Поправили фактический состав кастрюли: списываем/возвращаем только разницу.

        Полный откат и повторное списание исказили бы остаток, если между
        готовкой и правкой была инвентаризация (она уже учла израсходованное).
        Разница считается по ТОВАРУ (замена бренда того же товара — не расход),
        и сначала возвраты, потом новые списания — чтобы не было ложной недостачи.
        """
        by_key: dict[str, dict] = {}
        for grams_map, sign in ((old_grams, -1), (new_grams, 1)):
            for variant_id, grams in grams_map.items():
                product = await self._stock.product_for_variant(variant_id)
                if product is None:
                    continue
                entry = by_key.setdefault(product.item_key, {"product": product, "variant_id": variant_id, "diff": ZERO})
                entry["diff"] += sign * grams
                if sign > 0:
                    entry["product"], entry["variant_id"] = product, variant_id
        changes = [
            (e, quantize(grams_to_base(abs(e["diff"]), e["product"].base_unit, e["product"].piece_weight_g)))
            for e in by_key.values() if e["diff"] != 0
        ]
        for e, qty in changes:
            if e["diff"] < 0:
                await self._give_back(pot.id, e["product"].item_key, qty)
        for e, qty in changes:
            if e["diff"] > 0:
                await self._consume(
                    pot.household_id, e["product"], qty, "cook",
                    today=today, variant_id=e["variant_id"], pot_id=pot.id, user_id=user_id,
                )

    async def _give_back(self, pot_id: int, key: str, qty: Decimal) -> None:
        """Вернуть часть списанного кастрюлей: сперва гасим недостачу, потом партии с конца."""
        qty = quantize(qty)
        movements = [
            m for m in await self._stock.movements(pot_id=pot_id)
            if m.reason == "cook" and (await self._stock.product(m.product_id)).item_key == key
        ]
        movements.sort(key=lambda m: (m.lot_id is not None, -m.id))
        left = qty
        for m in movements:
            if left <= 0:
                break
            take = min(-_d(m.delta), left)
            if m.lot is not None:
                m.lot.remaining = _d(m.lot.remaining) + take
            m.delta = _d(m.delta) + take
            left -= take
            if _d(m.delta) == 0:
                await self._stock.delete_obj(m)
        await self._stock.flush()

    async def consume_portion(self, item: MealItem, portion: MealPortion, today: date) -> None:
        """«Съел» готовый продукт — порция уходит из запасов (блюда — через кастрюлю)."""
        if item.variant_id is None:
            return
        product = await self._stock.product_for_variant(item.variant_id)
        if product is None:
            return
        qty = grams_to_base(_d(portion.weight_g), product.base_unit, product.piece_weight_g)
        await self._consume(
            item.household_id, product, qty, "eat",
            today=today, variant_id=item.variant_id, portion_id=portion.id,
        )

    # ========================================================= ручные операции
    async def product(self, product_id: int) -> Product:
        product = await self._stock.product(product_id)
        if product is None:
            raise NotFoundError("Продукт не найден")
        return product

    async def _refuse_staple(self, household_id: int, product: Product) -> None:
        s = await self._stock.settings(household_id, product.item_key)
        if s is not None and s.is_staple:
            raise ValidationError(
                "Это базовый товар — его остаток не учитывается. "
                "Снимите отметку «базовый», чтобы вести запасы"
            )

    async def add_lot(
        self, household_id: int, user_id: int | None, data: LotAdd, *, source: str, today: date
    ) -> StockLot:
        product = await self.product(data.product_id)
        await self._refuse_staple(household_id, product)
        lot = StockLot(
            household_id=household_id,
            product_id=product.id,
            variant_id=data.variant_id,
            quantity=data.quantity,
            remaining=data.quantity,
            price=data.price,
            purchased_on=data.purchased_on or today,
            expires_on=data.expires_on,
            source=source,
            created_by_user_id=user_id,
        )
        self._stock.add(lot)
        await self._stock.flush()
        self._stock.add_movement(StockMovement(
            household_id=household_id, product_id=product.id, lot_id=lot.id, delta=data.quantity,
            reason="purchase" if source == "purchase" else source, created_by_user_id=user_id,
        ))
        await self._stock.flush()
        return lot

    # --- Пачки с кодами «Честного знака»: срок годности у каждой пачки свой ---
    async def parse_code(self, household_id: int, code: str) -> MarkParsed:
        """Прочитать код маркировки: штрихкод, срок, есть ли товар в справочнике и пачка в запасах."""
        info = parse_mark(code)
        if info is None:
            raise ValidationError("Это не код «Честного знака» — сканируйте квадратный код DataMatrix на упаковке")
        product = await self._stock.product_by_barcode(info.barcode)
        return MarkParsed(
            gtin=info.gtin, barcode=info.barcode, serial=info.serial, expires_on=info.expires_on,
            product_id=product.id if product else None, product_name=product.name if product else None,
            already_registered=await self._stock.mark_exists(household_id, info.gtin, info.serial),
        )

    async def _packs_by_expiry(
        self, household_id: int, product: Product, packs: list[PackIn]
    ) -> list[tuple[date | None, list[MarkInfo], int]]:
        """Пачки → группы по сроку: [(срок, [коды…], сколько пачек)]. Срок из кода важнее введённого.
        Проверяет: код читается, он от этого товара, пачку ещё не добавляли."""
        groups: dict[date | None, tuple[list[MarkInfo], int]] = {}
        seen: set[tuple[str, str]] = set()
        for p in packs:
            info = parse_mark(p.code) if p.code else None
            if p.code and info is None:
                raise ValidationError("Один из кодов не читается как код «Честного знака»")
            expires = p.expires_on
            if info is not None:
                if product.barcode and info.barcode != product.barcode:
                    raise ValidationError(
                        f"Код от другого товара (штрихкод {info.barcode}), а выбран «{product.name}»"
                    )
                if (info.gtin, info.serial) in seen or await self._stock.mark_exists(household_id, info.gtin, info.serial):
                    raise ConflictError("Эта пачка уже добавлена в запасы (код сканировали раньше)")
                seen.add((info.gtin, info.serial))
                expires = info.expires_on or expires
                if not product.barcode:
                    # штрихкода у товара ещё не было — запомним его по коду маркировки
                    if await self._stock.product_by_barcode(info.barcode) is None:
                        product.barcode = info.barcode
            marks, count = groups.get(expires, ([], 0))
            groups[expires] = (marks + ([info] if info else []), count + 1)
        return [(exp, marks, count) for exp, (marks, count) in groups.items()]

    def _attach_marks(self, household_id: int, lot: StockLot, marks: list[MarkInfo]) -> None:
        for m in marks:
            self._stock.add_mark(StockMark(
                household_id=household_id, lot_id=lot.id, gtin=m.gtin, serial=m.serial, expires_on=lot.expires_on,
            ))

    async def add_packs(
        self, household_id: int, user_id: int | None, data: PacksAdd, *, source: str, today: date
    ) -> list[StockLot]:
        """Покупка по пачкам: пачки с одним сроком — одна партия, с разными — разные.
        Цена делится между партиями пропорционально числу пачек."""
        product = await self.product(data.product_id)
        groups = await self._packs_by_expiry(household_id, product, data.packs)
        total_packs = sum(count for _, _, count in groups)
        lots, price_left = [], data.price
        for i, (expires, marks, count) in enumerate(groups):
            price = None
            if data.price is not None:
                last = i == len(groups) - 1
                price = price_left if last else (data.price * count / total_packs).quantize(Decimal("0.01"))
                price_left -= price
            lot = await self.add_lot(household_id, user_id, LotAdd(
                product_id=product.id, variant_id=data.variant_id, quantity=quantize(data.pack_amount * count),
                price=price, purchased_on=data.purchased_on, expires_on=expires,
            ), source=source, today=today)
            self._attach_marks(household_id, lot, marks)
            lots.append(lot)
        await self._stock.flush()
        return lots

    async def split_lot(self, household_id: int, lot_id: int, data: PacksSplit) -> None:
        """Разложить купленную партию по пачкам: пачки с другим сроком уходят в свои партии
        (с долей цены). Съеденное из партии остаётся в ней — отмены вернутся туда же."""
        lot = await self._stock.lot_of_household(household_id, lot_id)
        if lot is None:
            raise NotFoundError("Партия не найдена")
        groups = await self._packs_by_expiry(household_id, lot.product, data.packs)
        total = quantize(data.pack_amount * sum(count for _, _, count in groups))
        if total > quantize(_d(lot.remaining)):
            raise ValidationError(
                f"Пачек больше, чем осталось в партии: {total} > {quantize(_d(lot.remaining))}"
            )
        for i, (expires, marks, count) in enumerate(groups):
            qty = quantize(data.pack_amount * count)
            last = i == len(groups) - 1
            if last and qty == quantize(_d(lot.remaining)):
                # оставшиеся пачки — это и есть партия: просто ставим ей срок
                lot.expires_on = expires
                self._attach_marks(household_id, lot, marks)
                continue
            share = None
            if lot.price is not None and _d(lot.quantity) > 0:
                share = (_d(lot.price) * qty / _d(lot.quantity)).quantize(Decimal("0.01"))
                lot.price = _d(lot.price) - share
            lot.quantity = _d(lot.quantity) - qty
            lot.remaining = _d(lot.remaining) - qty
            part = StockLot(
                household_id=household_id, product_id=lot.product_id, variant_id=lot.variant_id,
                quantity=qty, remaining=qty, price=share, purchased_on=lot.purchased_on,
                expires_on=expires, source=lot.source, created_by_user_id=lot.created_by_user_id,
            )
            self._stock.add(part)
            await self._stock.flush()
            self._attach_marks(household_id, part, marks)
        await self._stock.flush()

    async def write_off(
        self, household_id: int, user_id: int | None, product_id: int, qty: Decimal, note: str | None, today: date
    ) -> None:
        """Испортилось/выбросили: списываем, но не больше, чем есть (без «недостачи»)."""
        product = await self.product(product_id)
        await self._refuse_staple(household_id, product)
        await self._consume(
            household_id, product, qty, "write_off",
            today=today, user_id=user_id, note=note, record_shortfall=False,
        )

    async def inventory(
        self, household_id: int, user_id: int | None, product_id: int, actual: Decimal, today: date
    ) -> None:
        """Пересчитали: остаток товара становится ровно actual; «учёт сбился» снимается."""
        product = await self.product(product_id)
        await self._refuse_staple(household_id, product)
        key = product.item_key
        total = sum((_d(lot.remaining) for lot in await self._stock.open_lots_for_key(household_id, key)), ZERO)
        if actual < total:
            await self._consume(
                household_id, product, total - actual, "inventory",
                today=today, user_id=user_id, record_shortfall=False,
            )
        elif actual > total:
            await self.add_lot(
                household_id, user_id, LotAdd(product_id=product.id, quantity=actual - total),
                source="inventory", today=today,
            )
        settings = await self._stock.get_or_create_settings(household_id, key)
        settings.needs_check = False
        await self._stock.flush()

    async def set_flags(self, household_id: int, product_id: int, data: ItemFlags) -> None:
        """Настройки товара семьи: базовый / заканчивается / «обычно берём» / снек."""
        product = await self.product(product_id)
        s = await self._stock.get_or_create_settings(household_id, product.item_key)
        if data.is_staple is not None:
            s.is_staple = data.is_staple
            if not data.is_staple:
                s.is_low = False
        if data.is_low is not None:
            s.is_low = data.is_low
        if data.regular is not None:
            s.regular = data.regular
        if "regular_qty" in data.model_fields_set:
            s.regular_qty = data.regular_qty or None
        if data.is_snack is not None:
            s.is_snack = data.is_snack
        await self._stock.flush()

    # ================================================================ сводка
    async def summary(self, household_id: int, today: date) -> list[StockItem]:
        """Запасы по товарам + базовые и «учёт сбился» даже без партий."""
        lots = await self._stock.open_lots(household_id)
        settings = await self._stock.settings_map(household_id)
        keys = {lot.product.item_key for lot in lots} | {
            k for k, s in settings.items() if s.is_staple or s.needs_check
        }
        products = {p.item_key: p for p in await self._stock.products_by_keys(keys)}
        items: list[StockItem] = []
        for key in keys:
            mine = [lot for lot in lots if lot.product.item_key == key]
            rep = mine[0].product if mine else products.get(key)
            if rep is None:
                continue
            s = settings.get(key)
            expiring = [lot.expires_on for lot in mine if lot.expires_on]
            items.append(StockItem(
                item_key=key,
                product_id=rep.id,
                name=rep.item.name if rep.item else rep.name,
                category_name=rep.category.name if rep.category else None,
                unit=rep.base_unit,
                piece_weight_g=rep.piece_weight_g,
                remaining=quantize(sum((_d(lot.remaining) for lot in mine), ZERO)),
                expired=quantize(sum((_d(lot.remaining) for lot in mine if lot.expires_on and lot.expires_on < today), ZERO)),
                nearest_expiry=min(expiring) if expiring else None,
                is_staple=bool(s and s.is_staple),
                is_low=bool(s and s.is_low),
                needs_check=bool(s and s.needs_check),
                regular=(s.regular if s and s.regular else "auto"),
                regular_qty=s.regular_qty if s else None,
                is_snack=bool(s and s.is_snack),
                lots=[LotResponse(
                    id=lot.id, product_id=lot.product_id, brand=brand_of(lot.product), variant_id=lot.variant_id,
                    quantity=lot.quantity, remaining=lot.remaining, price=lot.price,
                    purchased_on=lot.purchased_on, expires_on=lot.expires_on, source=lot.source,
                ) for lot in mine],
            ))
        items.sort(key=lambda i: ((i.category_name or ""), i.name))
        return items

    async def history(self, household_id: int, product_id: int) -> list[MovementResponse]:
        product = await self.product(product_id)
        return [
            MovementResponse(
                id=m.id, delta=m.delta, reason=m.reason, lot_id=m.lot_id, pot_id=m.pot_id,
                portion_id=m.portion_id, note=m.note, created_at=m.created_at,
            )
            for m in await self._stock.history(household_id, product.item_key)
        ]


def valid_unit(unit: str) -> str:
    if unit not in UNITS:
        raise ValidationError(f"Единица должна быть одной из {sorted(UNITS)}")
    return unit


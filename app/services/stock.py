"""Запасы семьи и общий список покупок.

Правила:
- запасы и потребность сверяются по ТОВАРУ (продукт без бренда, ключ —
  Product.search_name); партия помнит конкретный продукт, бренд и цену;
- расход: готовка списывает фактический состав кастрюли, «съел» готовый
  продукт — порцию; порядок партий: тот же бренд → тот же продукт →
  непросроченные с ближайшим сроком → самые старые;
- не хватило — списываем что есть, остаток записываем «недостачей»
  (движение без партии) и помечаем товар «учёт сбился», без ошибки;
- «базовые» товары (соль, масло) не учитываются вовсе;
- каждое изменение — движение; отмена (удалили кастрюлю, сняли «съел»)
  возвращает ровно то, что списали, в те же партии.
"""
from __future__ import annotations


from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.exceptions import NotFoundError, ValidationError
from app.domain import UNITS, grams_to_base, pick_packages, quantize
from app.models.plan import MealItem, MealPortion
from app.models.product import Product
from app.models.recipe import RecipeCookingLog
from app.models.stock import ShoppingLine, ShoppingList, StockLot, StockMovement
from app.repositories.plan import PlanRepository, remaining_weight
from app.repositories.recipe import RecipeRepository
from app.repositories.stock import ShoppingListRepository, StockRepository
from app.schemas.stock import (
    LineCheck,
    LineUpdate,
    LotAdd,
    LotResponse,
    MovementResponse,
    ShoppingItem,
    ShoppingLineResponse,
    ShoppingListOut,
    StockItem,
)

ZERO = Decimal("0")
FAR = date(9999, 12, 31)


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def brand_of(product: Product | None) -> str | None:
    return product.brand.name if product is not None and product.brand else None


@dataclass
class Need:
    """Потребность в товаре: граммы + продукт/бренд, по которому её посчитали."""

    grams: Decimal = ZERO
    product: Product | None = None
    variant_id: int | None = None


@dataclass
class Needs:
    by_key: dict[str, Need] = field(default_factory=dict)

    def add(self, product: Product | None, variant_id: int, grams: Decimal) -> None:
        if product is None or grams <= 0:
            return
        need = self.by_key.setdefault(product.search_name, Need(product=product, variant_id=variant_id))
        need.grams += grams


class StockService:
    def __init__(
        self,
        stock: StockRepository,
        lists: ShoppingListRepository,
        plan: PlanRepository,
        recipes: RecipeRepository,
    ) -> None:
        self._stock = stock
        self._lists = lists
        self._plan = plan
        self._recipes = recipes

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
        key = product.search_name
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
                entry = by_key.setdefault(product.search_name, {"product": product, "variant_id": variant_id, "diff": ZERO})
                entry["diff"] += sign * grams
                if sign > 0:
                    entry["product"], entry["variant_id"] = product, variant_id
        changes = [
            (e, quantize(grams_to_base(abs(e["diff"]), e["product"].base_unit, e["product"].piece_weight_g)))
            for e in by_key.values() if e["diff"] != 0
        ]
        for e, qty in changes:
            if e["diff"] < 0:
                await self._give_back(pot.id, e["product"].search_name, qty)
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
            if m.reason == "cook" and (await self._stock.product(m.product_id)).search_name == key
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
    async def _product(self, product_id: int) -> Product:
        product = await self._stock.product(product_id)
        if product is None:
            raise NotFoundError("Продукт не найден")
        return product

    async def _refuse_staple(self, household_id: int, product: Product) -> None:
        s = await self._stock.settings(household_id, product.search_name)
        if s is not None and s.is_staple:
            raise ValidationError(
                "Это базовый товар — его остаток не учитывается. "
                "Снимите отметку «базовый», чтобы вести запасы"
            )

    async def add_lot(
        self, household_id: int, user_id: int | None, data: LotAdd, *, source: str, today: date
    ) -> StockLot:
        product = await self._product(data.product_id)
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

    async def write_off(
        self, household_id: int, user_id: int | None, product_id: int, qty: Decimal, note: str | None, today: date
    ) -> None:
        """Испортилось/выбросили: списываем, но не больше, чем есть (без «недостачи»)."""
        product = await self._product(product_id)
        await self._refuse_staple(household_id, product)
        await self._consume(
            household_id, product, qty, "write_off",
            today=today, user_id=user_id, note=note, record_shortfall=False,
        )

    async def inventory(
        self, household_id: int, user_id: int | None, product_id: int, actual: Decimal, today: date
    ) -> None:
        """Пересчитали: остаток товара становится ровно actual; «учёт сбился» снимается."""
        product = await self._product(product_id)
        await self._refuse_staple(household_id, product)
        key = product.search_name
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

    async def set_flags(
        self, household_id: int, product_id: int, is_staple: bool | None, is_low: bool | None
    ) -> None:
        product = await self._product(product_id)
        s = await self._stock.get_or_create_settings(household_id, product.search_name)
        if is_staple is not None:
            s.is_staple = is_staple
            if not is_staple:
                s.is_low = False
        if is_low is not None:
            s.is_low = is_low
        await self._stock.flush()

    # ================================================================ сводка
    async def summary(self, household_id: int, today: date) -> list[StockItem]:
        """Запасы по товарам + базовые и «учёт сбился» даже без партий."""
        lots = await self._stock.open_lots(household_id)
        settings = await self._stock.settings_map(household_id)
        keys = {lot.product.search_name for lot in lots} | {
            k for k, s in settings.items() if s.is_staple or s.needs_check
        }
        products = {p.search_name: p for p in await self._stock.products_by_keys(keys)}
        items: list[StockItem] = []
        for key in keys:
            mine = [lot for lot in lots if lot.product.search_name == key]
            rep = mine[0].product if mine else products.get(key)
            if rep is None:
                continue
            s = settings.get(key)
            expiring = [lot.expires_on for lot in mine if lot.expires_on]
            items.append(StockItem(
                item_key=key,
                product_id=rep.id,
                name=rep.name,
                category_name=rep.category.name if rep.category else None,
                unit=rep.base_unit,
                piece_weight_g=rep.piece_weight_g,
                remaining=quantize(sum((_d(lot.remaining) for lot in mine), ZERO)),
                expired=quantize(sum((_d(lot.remaining) for lot in mine if lot.expires_on and lot.expires_on < today), ZERO)),
                nearest_expiry=min(expiring) if expiring else None,
                is_staple=bool(s and s.is_staple),
                is_low=bool(s and s.is_low),
                needs_check=bool(s and s.needs_check),
                lots=[LotResponse(
                    id=lot.id, product_id=lot.product_id, brand=brand_of(lot.product), variant_id=lot.variant_id,
                    quantity=lot.quantity, remaining=lot.remaining, price=lot.price,
                    purchased_on=lot.purchased_on, expires_on=lot.expires_on, source=lot.source,
                ) for lot in mine],
            ))
        items.sort(key=lambda i: ((i.category_name or ""), i.name))
        return items

    async def history(self, household_id: int, product_id: int) -> list[MovementResponse]:
        product = await self._product(product_id)
        return [
            MovementResponse(
                id=m.id, delta=m.delta, reason=m.reason, lot_id=m.lot_id, pot_id=m.pot_id,
                portion_id=m.portion_id, note=m.note, created_at=m.created_at,
            )
            for m in await self._stock.history(household_id, product.search_name)
        ]

    # ===================================================== потребность и покупки
    async def needs(self, household_id: int, start: date, end: date) -> Needs:
        """Несъеденные порции блюд без кастрюли в граммах, по товарам."""
        needs = Needs()
        if start > end:
            return needs
        items = await self._plan.list_in_range(household_id, start, end, only_unbought=True)
        recipes: dict[int, object] = {}
        products: dict[int, Product | None] = {}

        async def product_of(variant_id: int) -> Product | None:
            if variant_id not in products:
                products[variant_id] = await self._stock.product_for_variant(variant_id)
            return products[variant_id]

        for item in items:
            need = remaining_weight(item)
            if need <= 0:
                continue
            if item.variant_id is not None:
                needs.add(await product_of(item.variant_id), item.variant_id, need)
                continue
            if item.recipe_id is None:
                continue
            if item.recipe_id not in recipes:
                recipes[item.recipe_id] = await self._recipes.get_full(item.recipe_id)
            recipe = recipes[item.recipe_id]
            if recipe is None or _d(recipe.estimated_cooked_weight) <= 0:
                continue
            factor = need / _d(recipe.estimated_cooked_weight)
            for ing in recipe.template_ingredients:
                needs.add(await product_of(ing.variant_id), ing.variant_id, _d(ing.weight_g) * factor)
        return needs

    async def to_buy(self, household_id: int, start: date, end: date, today: date) -> list[ShoppingItem]:
        """Что купить на период: потребность − (запасы − то, что съедим до начала периода)."""
        if start > end:
            raise ValidationError("Дата окончания не может быть раньше даты начала")
        period = await self.needs(household_id, start, end)
        before = await self.needs(household_id, today, start - timedelta(days=1)) if start > today else Needs()
        # партии, которые испортятся до начала периода, запасом не считаем
        stock = await self._stock.available_by_key(household_id, max(today, start))
        settings = await self._stock.settings_map(household_id)
        low_staples = {k for k, s in settings.items() if s.is_staple and s.is_low}
        keys = set(period.by_key) | low_staples
        all_products = await self._stock.products_by_keys(keys)
        packages: dict[str, set[Decimal]] = {}
        reps: dict[str, Product] = {}
        for p in all_products:
            packages.setdefault(p.search_name, set()).update(_d(pk.amount) for pk in p.packages)
            reps.setdefault(p.search_name, p)

        out: list[ShoppingItem] = []
        for key in keys:
            need = period.by_key.get(key)
            product = need.product if need and need.product else reps.get(key)
            if product is None:
                continue
            s = settings.get(key)
            unit, piece = product.base_unit, product.piece_weight_g
            amounts = sorted(packages.get(key, set()))
            if s is not None and s.is_staple:
                if not s.is_low:
                    continue  # базовый и не заканчивается — не покупаем
                pkg_amount, pkg_count = (amounts[0], 1) if amounts else (None, None)
                out.append(self._item(product, need, unit, None, None, None, pkg_amount, pkg_count, staple=True))
                continue
            need_q = grams_to_base(need.grams, unit, piece) if need else ZERO
            before_need = before.by_key.get(key)
            before_q = grams_to_base(before_need.grams, unit, piece) if before_need else ZERO
            have = stock.get(key, ZERO)
            free = max(ZERO, have - before_q)
            buy = max(ZERO, need_q - free)
            if buy <= 0:
                continue
            pkg_amount, pkg_count = pick_packages(buy, amounts, unit)
            out.append(self._item(product, need, unit, need_q, free, buy, pkg_amount, pkg_count))
        out.sort(key=lambda i: ((i.category_name or ""), i.product_name))
        return out

    @staticmethod
    def _item(product, need, unit, need_q, free, buy, pkg_amount, pkg_count, staple=False) -> ShoppingItem:
        return ShoppingItem(
            item_key=product.search_name,
            product_id=product.id,
            variant_id=need.variant_id if need else None,
            product_name=product.name,
            brand=brand_of(product),
            category_name=product.category.name if product.category else None,
            unit=unit,
            need=quantize(need_q) if need_q is not None else None,
            in_stock=quantize(free) if free is not None else None,
            to_buy=quantize(buy) if buy is not None else None,
            package_amount=pkg_amount,
            package_count=pkg_count,
            is_staple=staple,
        )

    # =============================================== общий список покупок семьи
    async def active_list(self, household_id: int) -> ShoppingListOut | None:
        lst = await self._lists.active(household_id)
        return self._list_out(lst) if lst else None

    async def generate(
        self, household_id: int, start: date, end: date, today: date
    ) -> ShoppingListOut:
        """Сформировать/обновить активный список: отмеченное и добавленное вручную
        остаётся, расчётные неотмеченные строки пересчитываются с учётом запасов."""
        items = await self.to_buy(household_id, start, end, today)
        lst = await self._lists.active(household_id)
        if lst is None:
            lst = await self._lists.create_active(household_id, start, end)
        lst.start_date, lst.end_date = start, end
        for line in list(lst.lines):
            if not line.is_checked and not line.is_extra:
                lst.lines.remove(line)
        for it in items:
            lst.lines.append(ShoppingLine(
                product_id=it.product_id, variant_id=it.variant_id, needed=it.to_buy,
                package_amount=it.package_amount, package_count=it.package_count,
                is_staple=it.is_staple, is_extra=False, is_checked=False,
            ))
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def get_owned_list(self, list_id: int, household_id: int) -> ShoppingList:
        lst = await self._lists.get_full(list_id)
        if lst is None or lst.household_id != household_id:
            raise NotFoundError("Список покупок не найден")
        return lst

    async def get_owned_line(self, line_id: int, household_id: int) -> tuple[ShoppingList, ShoppingLine]:
        line = await self._lists.get_line(line_id)
        if line is None:
            raise NotFoundError("Строка списка не найдена")
        lst = await self.get_owned_list(line.list_id, household_id)
        return lst, next(x for x in lst.lines if x.id == line_id)

    async def add_extra(self, lst: ShoppingList, product_id: int, qty: Decimal | None) -> ShoppingListOut:
        product = await self._product(product_id)
        amounts = sorted(_d(p.amount) for p in product.packages)
        pkg_amount, pkg_count = pick_packages(qty, amounts, product.base_unit) if qty else (None, None)
        lst.lines.append(ShoppingLine(
            product_id=product.id, needed=qty, package_amount=pkg_amount, package_count=pkg_count,
            is_extra=True, is_checked=False, is_staple=False,
        ))
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def check(
        self, lst: ShoppingList, line: ShoppingLine, data: LineCheck, user_id: int | None, today: date
    ) -> ShoppingListOut:
        """«Куплено»: строка отмечается, товар сразу попадает в запасы партией."""
        if line.is_checked:
            raise ValidationError("Уже отмечено как купленное")
        if line.is_staple:
            # базовый товар: остаток не ведём — просто снимаем «заканчивается»
            product = await self._product(line.product_id)
            (await self._stock.get_or_create_settings(lst.household_id, product.search_name)).is_low = False
            line.is_checked = True
            line.checked_by_user_id = user_id
            line.checked_at = _now()
            lst.updated_at = _now()
            await self._lists.flush()
            return self._list_out(await self._lists.get_full(lst.id))
        qty = data.quantity
        if qty is None and line.package_amount and line.package_count:
            qty = _d(line.package_amount) * line.package_count
        if qty is None:
            qty = _d(line.needed)
        if not qty or qty <= 0:
            raise ValidationError("Укажите, сколько купили")
        lot = await self.add_lot(
            lst.household_id, user_id,
            LotAdd(product_id=line.product_id, variant_id=data.variant_id or line.variant_id, quantity=qty,
                   price=data.price, expires_on=data.expires_on),
            source="purchase", today=today,
        )
        line.lot_id = lot.id
        line.is_checked = True
        line.checked_by_user_id = user_id
        line.checked_at = _now()
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def uncheck(self, lst: ShoppingList, line: ShoppingLine) -> ShoppingListOut:
        """Снять «куплено»: партия убирается, если её ещё не трогали."""
        if not line.is_checked:
            raise ValidationError("Строка не отмечена")
        await self._drop_lot(line)
        line.is_checked = False
        line.checked_by_user_id = None
        line.checked_at = None
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def _drop_lot(self, line: ShoppingLine) -> None:
        if line.lot_id is None:
            return
        lot = await self._stock.get(line.lot_id)
        if lot is not None:
            if _d(lot.remaining) != _d(lot.quantity):
                raise ValidationError(
                    "Эта покупка уже частично израсходована — поправьте остаток в «Холодильник → Продукты»"
                )
            for m in await self._stock.lot_movements(lot.id):
                await self._stock.delete_obj(m)
            await self._stock.delete_obj(lot)
        line.lot_id = None
        await self._stock.flush()

    async def update_line(self, lst: ShoppingList, line: ShoppingLine, data: LineUpdate) -> ShoppingListOut:
        """Дозаполнить купленное: количество, цена, бренд, срок годности."""
        fields = data.model_dump(exclude_unset=True)
        if not line.is_checked or line.lot_id is None:
            if "quantity" in fields and data.quantity is not None:
                line.needed = data.quantity
                # подсказка по упаковкам должна следовать за новым количеством
                product = await self._product(line.product_id)
                amounts = sorted(_d(p.amount) for p in product.packages)
                line.package_amount, line.package_count = pick_packages(data.quantity, amounts, product.base_unit)
        else:
            lot = await self._stock.get(line.lot_id)
            if "quantity" in fields and data.quantity is not None:
                delta = data.quantity - _d(lot.quantity)
                if _d(lot.remaining) + delta < 0:
                    raise ValidationError("Из этой покупки уже израсходовано больше")
                lot.quantity = data.quantity
                lot.remaining = _d(lot.remaining) + delta
                for m in await self._stock.lot_movements(lot.id):
                    if m.reason == "purchase":
                        m.delta = data.quantity
            if "price" in fields:
                lot.price = data.price
            if "expires_on" in fields:
                lot.expires_on = data.expires_on
            if "variant_id" in fields:
                lot.variant_id = data.variant_id
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def delete_line(self, lst: ShoppingList, line: ShoppingLine) -> ShoppingListOut:
        if line.is_checked:
            await self._drop_lot(line)
        lst.lines.remove(line)
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def close(self, lst: ShoppingList) -> None:
        lst.status = "closed"
        lst.closed_at = _now()
        await self._lists.flush()

    @staticmethod
    def _list_out(lst: ShoppingList) -> ShoppingListOut:
        lines = []
        for line in lst.lines:
            p = line.product
            lot = line.lot
            lines.append(ShoppingLineResponse(
                id=line.id,
                item_key=p.search_name if p else None,
                product_id=line.product_id,
                variant_id=line.variant_id,
                product_name=p.name if p else f"Продукт #{line.product_id}",
                brand=brand_of(p),
                category_name=p.category.name if p and p.category else None,
                unit=p.base_unit if p else "g",
                needed=line.needed,
                package_amount=line.package_amount,
                package_count=line.package_count,
                is_extra=line.is_extra,
                is_staple=line.is_staple,
                is_checked=line.is_checked,
                checked_at=line.checked_at,
                bought_quantity=lot.quantity if lot else None,
                price=lot.price if lot else None,
                expires_on=lot.expires_on if lot else None,
                lot_variant_id=lot.variant_id if lot else None,
            ))
        lines.sort(key=lambda x: (x.is_checked, x.category_name or "", x.product_name))
        return ShoppingListOut(
            id=lst.id, start_date=lst.start_date, end_date=lst.end_date, status=lst.status,
            updated_at=lst.updated_at, lines=lines,
        )


def valid_unit(unit: str) -> str:
    if unit not in UNITS:
        raise ValidationError(f"Единица должна быть одной из {sorted(UNITS)}")
    return unit

"""Покупки семьи: потребность плана, «что купить» и общий список с отметками «куплено».

- потребность = несъеденные порции блюд без кастрюли (рецепт — целыми закладками) и готовых продуктов;
- купить = потребность периода − (свободные запасы − то, что съедим до начала периода), до целых упаковок
  (с допуском семьи);
- список общий для семьи, «куплено» сразу кладёт партию в запасы (StockService.add_lot);
  ручные добавки (added / «вне плана») переживают «Пересчитать».
"""
from __future__ import annotations


from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.core import clock
from app.core.exceptions import NotFoundError, ValidationError
from app.domain import _ceil, dec, grams_to_base, pick_packages, quantize
from app.models.product import Product
from app.models.stock import ShoppingLine, ShoppingList
from app.repositories.plan import PlanRepository
from app.services.pots import remaining_weight
from app.repositories.recipe import RecipeRepository
from app.repositories.stock import ShoppingListRepository, StockRepository
from app.services.naming import brand_of
from app.services.stock import StockService
from app.schemas.stock import (
    LineCheck,
    LineUpdate,
    LotAdd,
    ShoppingItem,
    ShoppingLineResponse,
    ShoppingListOut,
)

ZERO = Decimal("0")

_d = dec
_now = clock.utc_now


@dataclass
class Need:
    """Потребность в товаре: граммы + продукт/бренд, по которому её посчитали."""

    grams: Decimal = ZERO
    product: Product | None = None
    variant_id: int | None = None
    exact: bool = False          # «именно этот вариант»: этот продукт, а не любой того же товара


@dataclass
class Needs:
    by_key: dict[str, Need] = field(default_factory=dict)

    def add(self, product: Product | None, variant_id: int, grams: Decimal, exact: bool = False) -> None:
        """Обычная потребность — по товару (любой бренд), «точная» — по товару и продукту."""
        if product is None or grams <= 0:
            return
        key = exact_key(product) if exact else product.item_key
        need = self.by_key.setdefault(key, Need(product=product, variant_id=variant_id, exact=exact))
        need.grams += grams


def exact_key(product: Product) -> str:
    """Ключ «именно этот вариант»: товар + продукт («кефир 3,2%#17»)."""
    return exact_key_of(product.item_key, product.id)


def exact_key_of(item_key: str, product_id: int) -> str:
    return f"{item_key}#{product_id}"



class ShoppingService:
    def __init__(
        self,
        stock: StockRepository,
        lists: ShoppingListRepository,
        plan: PlanRepository,
        recipes: RecipeRepository,
        stock_service: StockService,
    ) -> None:
        self._stock = stock
        self._lists = lists
        self._plan = plan
        self._recipes = recipes
        self._stock_svc = stock_service

    # ===================================================== потребность и покупки
    async def needs(self, household_id: int, start: date, end: date) -> Needs:
        """Несъеденные порции блюд без кастрюли в граммах, по товарам."""
        needs = Needs()
        if start > end:
            return needs
        items = await self._plan.list_in_range(household_id, start, end, only_unbought=True)
        products: dict[int, Product | None] = {}

        async def product_of(variant_id: int) -> Product | None:
            if variant_id not in products:
                products[variant_id] = await self._stock.product_for_variant(variant_id)
            return products[variant_id]

        # Рецепт готовят целой кастрюлей: за период складываем недоеденное по рецепту
        # и округляем вверх до целых закладок (1 порция из 4 — всё равно вся закладка;
        # остаток ляжет в холодильник и закроет следующие планы)
        recipe_need: dict[int, Decimal] = {}
        for item in items:
            need = remaining_weight(item)
            if need <= 0:
                continue
            if item.variant_id is not None:
                needs.add(await product_of(item.variant_id), item.variant_id, need, exact=bool(item.exact))
            elif item.recipe_id is not None:
                recipe_need[item.recipe_id] = recipe_need.get(item.recipe_id, ZERO) + need
        recipes = await self._recipes.get_many_full(set(recipe_need))
        for recipe_id, need in recipe_need.items():
            recipe = recipes.get(recipe_id)
            if recipe is None or _d(recipe.estimated_cooked_weight) <= 0:
                continue
            portions = quantize(need / _d(recipe.estimated_cooked_weight), "0.001")
            # «можно половиной» — шаг полкастрюли, иначе — целая
            step = Decimal("0.5") if recipe.allow_half else Decimal(1)
            batches = Decimal(_ceil(portions / step)) * step
            for ing in recipe.template_ingredients:
                needs.add(await product_of(ing.variant_id), ing.variant_id, _d(ing.weight_g) * batches, exact=bool(ing.exact))
        return needs

    async def to_buy(self, household_id: int, start: date, end: date, today: date) -> list[ShoppingItem]:
        """Что купить на период: потребность − (запасы − то, что съедим до начала периода)."""
        if start > end:
            raise ValidationError("Дата окончания не может быть раньше даты начала")
        period = await self.needs(household_id, start, end)
        before = await self.needs(household_id, today, start - timedelta(days=1)) if start > today else Needs()
        # партии, которые испортятся до начала периода, запасом не считаем
        as_of = max(today, start)
        stock = await self._stock.available_by_key(household_id, as_of)
        stock_by_product = await self._stock.available_by_product(household_id, as_of)
        settings = await self._stock.settings_map(household_id)
        low_staples = {k for k, s in settings.items() if s.is_staple and s.is_low}
        keys = set(period.by_key) | low_staples
        item_keys = {k.split("#", 1)[0] for k in keys}
        all_products = await self._stock.products_by_keys(item_keys)
        packages: dict[str, set[Decimal]] = {}
        reps: dict[str, Product] = {}
        by_id: dict[int, Product] = {}
        for p in all_products:
            packages.setdefault(p.item_key, set()).update(_d(pk.amount) for pk in p.packages)
            reps.setdefault(p.item_key, p)
            by_id[p.id] = p
        # «обычно берёте» — по последней покупке; иначе — продукт из плана/рецепта
        usual = await self._stock.usual_products(household_id, item_keys)
        used_by_exact: dict[str, Decimal] = {}
        tolerance = await self._stock.tolerance(household_id)

        out: list[ShoppingItem] = []
        # сначала «именно этот вариант»: берут только из партий своего продукта,
        # остальное по товару достаётся обычной потребности
        for key in sorted(keys, key=lambda k: "#" not in k):
            need = period.by_key.get(key)
            item_key = key.split("#", 1)[0]
            exact = bool(need and need.exact)
            product = need.product if need and need.product else reps.get(item_key)
            if product is None:
                continue
            s = settings.get(item_key)
            unit, piece = product.base_unit, product.piece_weight_g
            amounts = sorted(packages.get(item_key, set()))
            if s is not None and s.is_staple:
                if not s.is_low or "#" in key:
                    continue  # базовый и не заканчивается — не покупаем (и без «точных» строк)
                pkg_amount, pkg_count = (amounts[0], 1) if amounts else (None, None)
                shown = by_id.get(usual.get(item_key)) or product
                out.append(self._item(shown, need, unit, None, None, None, pkg_amount, pkg_count, staple=True))
                continue
            need_q = grams_to_base(need.grams, unit, piece) if need else ZERO
            before_need = before.by_key.get(key)
            before_q = grams_to_base(before_need.grams, unit, piece) if before_need else ZERO
            if exact:
                have = stock_by_product.get(product.id, ZERO)
                used_by_exact[item_key] = used_by_exact.get(item_key, ZERO) + min(have, before_q + need_q)
            else:
                have = max(ZERO, stock.get(item_key, ZERO) - used_by_exact.get(item_key, ZERO))
            free = max(ZERO, have - before_q)
            buy = max(ZERO, need_q - free)
            # недостаёт немного (в пределах допуска семьи) того, что уже есть, — не покупаем
            if buy <= 0 or (free > 0 and buy <= need_q * tolerance):
                continue
            pkg_amount, pkg_count = pick_packages(buy, amounts, unit, tolerance)
            shown = product if exact else (by_id.get(usual.get(item_key)) or product)
            out.append(self._item(shown, need if exact or shown is product else None, unit, need_q, free, buy,
                                  pkg_amount, pkg_count, exact=exact))
        out.sort(key=lambda i: ((i.category_name or ""), i.product_name))
        return out

    @staticmethod
    def _item(product, need, unit, need_q, free, buy, pkg_amount, pkg_count, staple=False, exact=False) -> ShoppingItem:
        # обычная строка — по товару («Кефир 3,2%»), «именно этот» — продукт с брендом
        return ShoppingItem(
            item_key=product.item_key,
            product_id=product.id,
            variant_id=need.variant_id if need else None,
            product_name=product.name if exact or product.item is None else product.item.name,
            is_exact=exact,
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
        """Сформировать/обновить активный список: отмеченное остаётся, расчётные строки
        пересчитываются с учётом запасов, а добавленное вручную («ещё йогурт») сохраняется
        и прибавляется к строке того же товара — одна строка на товар."""
        items = await self.to_buy(household_id, start, end, today)
        lst = await self._lists.active(household_id)
        if lst is None:
            lst = await self._lists.create_active(household_id, start, end)
        lst.start_date, lst.end_date = start, end
        # ручные добавки неотмеченных строк: ключ товара → (количество, продукт)
        manual: dict[str, tuple[Decimal, int]] = {}
        for line in list(lst.lines):
            if line.is_checked:
                continue
            extra = _d(line.needed) if line.is_extra else _d(line.added)
            if extra > 0:
                key = exact_key(line.product) if line.is_exact else line.product.item_key
                qty, pid = manual.get(key, (ZERO, line.product_id))
                manual[key] = (qty + extra, pid if not line.is_extra else line.product_id)
            lst.lines.remove(line)
        for it in items:
            key = exact_key_of(it.item_key, it.product_id) if it.is_exact else it.item_key
            add, _ = manual.pop(key, (ZERO, None))
            needed, pkg_amount, pkg_count = it.to_buy, it.package_amount, it.package_count
            if add > 0:
                needed = _d(needed) + add
                pkg_amount, pkg_count = await self.packages_for(it.product_id, needed)
            lst.lines.append(ShoppingLine(
                product_id=it.product_id, variant_id=it.variant_id, needed=needed,
                package_amount=pkg_amount, package_count=pkg_count, added=add or None,
                is_staple=it.is_staple, is_extra=False, is_checked=False, is_exact=it.is_exact,
            ))
        for key, (qty, pid) in manual.items():
            pkg_amount, pkg_count = await self.packages_for(pid, qty)
            lst.lines.append(ShoppingLine(
                product_id=pid, needed=qty, package_amount=pkg_amount, package_count=pkg_count,
                is_extra=True, is_checked=False, is_staple=False, is_exact="#" in key,
            ))
        lst.updated_at = _now()
        await self._lists.flush()
        return self._list_out(await self._lists.get_full(lst.id))

    async def packages_for(self, product_id: int, qty: Decimal) -> tuple[Decimal | None, int | None]:
        """Упаковки под количество — по всем брендам товара (как в расчёте покупок)."""
        product = await self._stock_svc.product(product_id)
        amounts = sorted({_d(pk.amount) for p in await self._stock.products_by_keys({product.item_key}) for pk in p.packages})
        return pick_packages(qty, amounts, product.base_unit)

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

    async def add_extra(
        self, lst: ShoppingList, product_id: int, qty: Decimal | None, *, merge: bool = True
    ) -> ShoppingListOut:
        """Внеплановая покупка. Товар уже есть в списке (неотмеченным) — прибавляем к его
        строке, а не плодим вторую; иначе — строка «вне плана». Без количества — одна упаковка.
        merge=False — всегда отдельной строкой (чек: её сразу отметят купленной)."""
        product = await self._stock_svc.product(product_id)
        if not qty:
            qty, _ = await self.packages_for(product.id, Decimal("0.1"))
            if not qty:
                raise ValidationError("Укажите, сколько купить")
        same = None if not merge else next((
            ln for ln in lst.lines
            if not ln.is_checked and not ln.is_staple and ln.product.item_key == product.item_key
            and (not ln.is_exact or ln.product_id == product.id)
        ), None)
        if same is not None:
            same.needed = _d(same.needed) + qty
            if not same.is_extra:
                same.added = _d(same.added) + qty
            same.package_amount, same.package_count = await self.packages_for(same.product_id, _d(same.needed))
        else:
            pkg_amount, pkg_count = await self.packages_for(product.id, qty)
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
            product = await self._stock_svc.product(line.product_id)
            (await self._stock.get_or_create_settings(lst.household_id, product.item_key)).is_low = False
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
        variant_id = data.variant_id or line.variant_id
        if data.product_id and data.product_id != line.product_id:
            # обычная строка — по товару: можно купить любой бренд, но не другой товар
            if line.is_exact:
                raise ValidationError("В этой строке нужен именно этот вариант продукта")
            bought = await self._stock_svc.product(data.product_id)
            current = await self._stock_svc.product(line.product_id)
            if bought.item_key != current.item_key:
                raise ValidationError(f"«{bought.name}» — другой товар, а в строке «{current.item.name if current.item else current.name}»")
            line.product_id = bought.id
            variant_id = data.variant_id   # версия КБЖУ строки относилась к прежнему бренду
        lot = await self._stock_svc.add_lot(
            lst.household_id, user_id,
            LotAdd(product_id=line.product_id, variant_id=variant_id, quantity=qty,
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
                product = await self._stock_svc.product(line.product_id)
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
            if data.product_id and data.product_id != lot.product_id:
                if line.is_exact:
                    raise ValidationError("В этой строке нужен именно этот вариант продукта")
                bought = await self._stock_svc.product(data.product_id)
                current = await self._stock_svc.product(lot.product_id)
                if bought.item_key != current.item_key:
                    raise ValidationError(f"«{bought.name}» — другой товар")
                lot.product_id = line.product_id = bought.id
                if "variant_id" not in fields:
                    lot.variant_id = None   # версия КБЖУ была от прежнего бренда
                for m in await self._stock.lot_movements(lot.id):
                    m.product_id = bought.id
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
                item_key=p.item_key if p else None,
                product_id=line.product_id,
                variant_id=line.variant_id,
                # обычная строка — название товара, «именно этот» и «вне плана» — продукт с брендом
                product_name=(p.item.name if p and p.item and not (line.is_exact or line.is_extra)
                              else p.name if p else f"Продукт #{line.product_id}"),
                is_exact=line.is_exact,
                added=line.added,
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


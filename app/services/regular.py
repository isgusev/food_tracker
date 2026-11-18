"""«Обычно берём» и снеки (docs/AUTOPLAN.md, 5): товары, которые покупают почти каждую неделю,
и квота на снеки и сладкое."""
from __future__ import annotations


from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from app.core.exceptions import ValidationError
from app.domain import dec, monday, quantize
from app.models.product import Product
from app.models.stock import StockLot
from app.repositories.household import HouseholdRepository
from app.repositories.stock import ShoppingListRepository, StockRepository
from app.schemas.stock import RegularItem, RegularOut, SnackQuota
from app.services.shopping import ShoppingService

ZERO = Decimal("0")
REGULAR_WEEKS = 8                 # окно истории покупок, недель
REGULAR_SHARE = Decimal("0.5")    # покупали не реже чем в половине недель

_d = dec


def is_snack(product: Product, settings, snack_categories: set[int]) -> bool:
    """Снек/сладкое: категория продукта отмечена у семьи или товар помечен «снек»."""
    return bool((settings is not None and settings.is_snack) or (product.category_id in snack_categories))


class RegularService:
    def __init__(
        self, stock: StockRepository, lists: ShoppingListRepository, households: HouseholdRepository,
        shopping: ShoppingService,
    ) -> None:
        self._stock = stock
        self._lists = lists
        self._households = households
        self._shopping = shopping

    async def snack_spent(self, household_id: int, start: date, end: date) -> Decimal:
        """Сколько потрачено на снеки и сладкое за дни start…end."""
        planner = await self._households.planner(household_id)
        cats = set(planner.snack_categories or []) if planner else set()
        settings = await self._stock.settings_map(household_id)
        return sum((
            _d(lot.price) for lot in await self._stock.purchases_between(household_id, start, end)
            if lot.price is not None and is_snack(lot.product, settings.get(lot.product.item_key), cats)
        ), ZERO)

    async def regular(self, household_id: int, start: date, end: date, today: date) -> RegularOut:
        """«Обычно берём» на период (docs/AUTOPLAN.md, 5): товары, купленные в ≥ половине из 8 последних
        полных недель; количество — медиана в неделю × недель периода − запасы − уже в активном списке.
        always/never и своё количество — из настроек товара. Снеки сверх квоты недели не предлагаются."""
        if start > end:
            raise ValidationError("Дата окончания не может быть раньше даты начала")
        w0 = monday(today) - timedelta(weeks=REGULAR_WEEKS)
        lots = await self._stock.purchases_between(household_id, w0, monday(today) - timedelta(days=1))
        settings = await self._stock.settings_map(household_id)
        planner = await self._households.planner(household_id)
        cats = set(planner.snack_categories or []) if planner else set()
        quota = _d(planner.snack_quota) if planner and planner.snack_quota else None

        weekly: dict[str, dict[int, Decimal]] = {}
        last: dict[str, StockLot] = {}
        price: dict[str, Decimal] = {}
        for lot in lots:
            key = lot.product.item_key
            wk = (lot.purchased_on - w0).days // 7
            weekly.setdefault(key, {})
            weekly[key][wk] = weekly[key].get(wk, ZERO) + _d(lot.quantity)
            last[key] = lot
            if lot.price is not None and _d(lot.quantity) > 0:
                price[key] = _d(lot.price) / _d(lot.quantity)
        keys = {k for k, w in weekly.items() if len(w) >= REGULAR_WEEKS * REGULAR_SHARE}
        keys |= {k for k, st in settings.items() if st.regular == "always"}
        keys = {k for k in keys if not (settings.get(k) and (settings[k].regular == "never" or settings[k].is_staple))}
        if not keys:
            return RegularOut(items=[], snacks=SnackQuota(quota=quota))

        products = {}
        for p in await self._stock.products_by_keys(keys):
            products.setdefault(p.item_key, p)
        stock = await self._stock.available_by_key(household_id, max(today, start))
        lst = await self._lists.active(household_id)
        in_list: dict[str, Decimal] = {}
        for line in (lst.lines if lst else []):
            if not line.is_checked:
                k = line.product.item_key
                in_list[k] = in_list.get(k, ZERO) + _d(line.needed)
        weeks = max(1, round(((end - start).days + 1) / 7))

        found: list[RegularItem] = []
        for key in keys:
            st = settings.get(key)
            product = last[key].product if key in last else products.get(key)
            if product is None:
                continue
            history = weekly.get(key, {})
            per_week = _d(st.regular_qty) if st and st.regular_qty else (
                Decimal(str(median(history.values()))) if history else None)
            if not per_week:
                continue
            need = quantize(per_week * weeks - stock.get(key, ZERO) - in_list.get(key, ZERO))
            if need <= 0:
                continue
            pkg_amount, pkg_count = await self._shopping.packages_for(product.id, need)
            qty = _d(pkg_amount) * pkg_count if pkg_amount and pkg_count else need
            found.append(RegularItem(
                item_key=key, product_id=product.id, name=product.item.name if product.item else product.name,
                unit=product.base_unit, weekly=quantize(per_week), to_buy=need,
                package_amount=pkg_amount, package_count=pkg_count, weeks_bought=len(history),
                weeks=REGULAR_WEEKS, always=bool(st and st.regular == "always"),
                is_snack=is_snack(product, st, cats),
                est_price=quantize(price[key] * qty, "0.01") if key in price else None,
            ))
        found.sort(key=lambda r: (not r.always, -r.weeks_bought, r.name))
        # квота снеков: потрачено за эту неделю + то, что предложим, — не больше квоты
        spent = await self.snack_spent(household_id, monday(today), today)
        running, hidden, out = spent, 0, []
        for r in found:
            if r.is_snack and quota is not None:
                if running + _d(r.est_price) > quota:
                    hidden += 1
                    continue
                running += _d(r.est_price)
            out.append(r)
        return RegularOut(items=out, snacks=SnackQuota(spent=quantize(spent, "0.01"), quota=quota, hidden=hidden))


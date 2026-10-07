"""Репозитории запасов семьи и общего списка покупок."""
from __future__ import annotations


from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.product import Product, ProductManufacturer, ProductVariant
from app.models.stock import (
    HouseholdProduct,
    ShoppingLine,
    ShoppingList,
    StockLot,
    StockMovement,
)
from app.repositories.base import BaseRepository


class StockRepository(BaseRepository[StockLot]):
    model = StockLot

    # --- товары и продукты ---
    async def product(self, product_id: int) -> Product | None:
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.packages), joinedload(Product.brand), joinedload(Product.category))
        )
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def product_for_variant(self, variant_id: int) -> Product | None:
        stmt = (
            select(Product)
            .join(ProductManufacturer, ProductManufacturer.product_id == Product.id)
            .join(ProductVariant, ProductVariant.manufacturer_id == ProductManufacturer.id)
            .where(ProductVariant.id == variant_id)
            .options(selectinload(Product.packages), joinedload(Product.brand), joinedload(Product.category))
        )
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def products_by_keys(self, keys: set[str]) -> list[Product]:
        """Все продукты (любых брендов) указанных товаров — для упаковок и единиц."""
        if not keys:
            return []
        stmt = (
            select(Product)
            .where(Product.search_name.in_(keys))
            .options(selectinload(Product.packages), joinedload(Product.brand), joinedload(Product.category))
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    # --- настройки товара в семье ---
    async def settings(self, household_id: int, key: str) -> HouseholdProduct | None:
        return await self._session.get(HouseholdProduct, (household_id, key))

    async def settings_map(self, household_id: int) -> dict[str, HouseholdProduct]:
        stmt = select(HouseholdProduct).where(HouseholdProduct.household_id == household_id)
        return {s.item_key: s for s in (await self._session.execute(stmt)).scalars().all()}

    async def get_or_create_settings(self, household_id: int, key: str) -> HouseholdProduct:
        s = await self.settings(household_id, key)
        if s is None:
            s = HouseholdProduct(household_id=household_id, item_key=key, is_staple=False, is_low=False, needs_check=False)
            self._session.add(s)
            await self._session.flush()
        return s

    # --- партии ---
    def _lots_query(self, household_id: int):
        return (
            select(StockLot)
            .join(Product, Product.id == StockLot.product_id)
            .where(StockLot.household_id == household_id)
            .options(joinedload(StockLot.product).options(selectinload(Product.packages), joinedload(Product.brand), joinedload(Product.category)))
        )

    async def open_lots(self, household_id: int) -> list[StockLot]:
        stmt = self._lots_query(household_id).where(StockLot.remaining > 0).order_by(StockLot.id)
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def open_lots_for_key(self, household_id: int, key: str) -> list[StockLot]:
        stmt = (
            self._lots_query(household_id)
            .where(Product.search_name == key, StockLot.remaining > 0)
            .order_by(StockLot.id)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def available_by_key(self, household_id: int, as_of: date) -> dict[str, Decimal]:
        """Свободный остаток по товарам: непросроченные партии на дату."""
        stmt = (
            select(Product.search_name, StockLot.remaining)
            .join(Product, Product.id == StockLot.product_id)
            .where(
                StockLot.household_id == household_id,
                StockLot.remaining > 0,
                or_(StockLot.expires_on.is_(None), StockLot.expires_on >= as_of),
            )
        )
        out: dict[str, Decimal] = {}
        for key, remaining in (await self._session.execute(stmt)).all():
            out[key] = out.get(key, Decimal("0")) + Decimal(str(remaining))
        return out

    # --- движения ---
    def add_movement(self, m: StockMovement) -> None:
        self._session.add(m)

    async def movements(self, *, pot_id: int | None = None, portion_id: int | None = None) -> list[StockMovement]:
        stmt = select(StockMovement).options(joinedload(StockMovement.lot))
        if pot_id is not None:
            stmt = stmt.where(StockMovement.pot_id == pot_id)
        if portion_id is not None:
            stmt = stmt.where(StockMovement.portion_id == portion_id)
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def lot_movements(self, lot_id: int) -> list[StockMovement]:
        stmt = select(StockMovement).where(StockMovement.lot_id == lot_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def history(self, household_id: int, key: str, limit: int = 100) -> list[StockMovement]:
        stmt = (
            select(StockMovement)
            .join(Product, Product.id == StockMovement.product_id)
            .where(StockMovement.household_id == household_id, Product.search_name == key)
            .order_by(StockMovement.id.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete_obj(self, obj) -> None:
        await self._session.delete(obj)


class ShoppingListRepository(BaseRepository[ShoppingList]):
    model = ShoppingList

    def _full(self):
        return select(ShoppingList).options(
            selectinload(ShoppingList.lines).options(
                joinedload(ShoppingLine.product).options(
                    selectinload(Product.packages), joinedload(Product.brand), joinedload(Product.category)
                ),
                joinedload(ShoppingLine.lot),
            )
        )

    async def active(self, household_id: int) -> ShoppingList | None:
        stmt = (
            self._full()
            .where(ShoppingList.household_id == household_id, ShoppingList.status == "active")
            .order_by(ShoppingList.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def get_full(self, list_id: int) -> ShoppingList | None:
        stmt = self._full().where(ShoppingList.id == list_id).execution_options(populate_existing=True)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def get_line(self, line_id: int) -> ShoppingLine | None:
        return await self._session.get(ShoppingLine, line_id)

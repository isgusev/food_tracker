"""Репозиторий товаров (базовых наименований) и их настроек в семьях."""
from __future__ import annotations


from sqlalchemy import select, update
from sqlalchemy.orm import joinedload, selectinload

from app.models.product import Item, Product
from app.models.stock import HouseholdProduct
from app.repositories.base import BaseRepository


class ItemRepository(BaseRepository[Item]):
    model = Item

    async def all_with_products(self) -> list[Item]:
        stmt = (
            select(Item)
            .options(selectinload(Item.products).options(joinedload(Product.brand), selectinload(Product.packages)))
            .order_by(Item.name)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def get_full(self, key: str) -> Item | None:
        stmt = (
            select(Item).where(Item.key == key)
            .options(selectinload(Item.products).options(joinedload(Product.brand), selectinload(Product.packages)))
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def get_by_key(self, key: str) -> Item | None:
        return await self._session.get(Item, key)

    async def products_of(self, keys: list[str]) -> list[Product]:
        stmt = select(Product).where(Product.item_key.in_(keys)).options(selectinload(Product.packages))
        return list((await self._session.execute(stmt)).scalars().all())

    async def has_products(self, key: str) -> bool:
        return (await self._session.execute(select(Product.id).where(Product.item_key == key).limit(1))).first() is not None

    async def settings_of(self, keys: list[str]) -> list[HouseholdProduct]:
        stmt = select(HouseholdProduct).where(HouseholdProduct.item_key.in_(keys))
        return list((await self._session.execute(stmt)).scalars().all())

    async def rekey_setting(self, row: HouseholdProduct, new_key: str) -> None:
        """item_key — часть первичного ключа: переносим явным UPDATE."""
        await self._session.execute(
            update(HouseholdProduct)
            .where(HouseholdProduct.household_id == row.household_id, HouseholdProduct.item_key == row.item_key)
            .values(item_key=new_key)
        )
        await self._session.refresh(row)

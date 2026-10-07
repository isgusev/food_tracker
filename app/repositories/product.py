"""Репозитории каталога продуктов."""
from __future__ import annotations


from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.product import (
    Brand,
    Product,
    ProductCategory,
    ProductManufacturer,
    ProductPackage,
    ProductVariant,
)
from app.repositories.base import BaseRepository


class ProductCategoryRepository(BaseRepository[ProductCategory]):
    model = ProductCategory

    async def get_by_name_ilike(self, name: str) -> ProductCategory | None:
        """Без учёта регистра — сравнением в Python: SQL LOWER/ILIKE не понимает
        кириллицу в SQLite, а collation PostgreSQL может отличаться от .lower()."""
        target = name.strip().lower()
        for category in (await self._session.execute(select(ProductCategory))).scalars().all():
            if category.name.strip().lower() == target:
                return category
        return None


class BrandRepository(BaseRepository[Brand]):
    model = Brand

    async def get_by_search_name(self, search_name: str) -> Brand | None:
        stmt = select(Brand).where(Brand.search_name == search_name)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class ProductRepository(BaseRepository[Product]):
    model = Product

    def full_query(self):
        """Загрузка продукта со всем деревом каталога одним JOIN'ом (лечит N+1)."""
        return select(Product).options(
            joinedload(Product.brand),
            joinedload(Product.manufacturers).joinedload(ProductManufacturer.variants),
            selectinload(Product.packages),
        )

    async def same_item(self, search_name: str) -> list[Product]:
        """Все продукты одного товара (одно название, разные бренды)."""
        stmt = select(Product).where(Product.search_name == search_name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_package(self, package_id: int) -> ProductPackage | None:
        return await self._session.get(ProductPackage, package_id)

    async def get_full(self, product_id: int) -> Product | None:
        stmt = self.full_query().where(Product.id == product_id).execution_options(populate_existing=True)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def list_full(
        self, limit: int = 100, offset: int = 0, q: str | None = None
    ) -> list[Product]:
        stmt = self.full_query()
        if q and q.strip():
            # search_name/brand.search_name хранятся в нижнем регистре (Python .lower()),
            # поэтому сравниваем без SQL LOWER() — он не работает с кириллицей в SQLite
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.join(Brand, Product.brand_id == Brand.id).where(
                or_(Product.search_name.like(needle), Brand.search_name.like(needle))
            )
        stmt = stmt.order_by(Product.name, Product.id).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def find_duplicate(self, brand_id: int, search_name: str) -> Product | None:
        stmt = select(Product).where(
            Product.brand_id == brand_id, Product.search_name == search_name
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class ManufacturerRepository(BaseRepository[ProductManufacturer]):
    model = ProductManufacturer

    async def get_for_product(self, manufacturer_id: int, product_id: int) -> ProductManufacturer | None:
        stmt = select(ProductManufacturer).where(
            ProductManufacturer.id == manufacturer_id,
            ProductManufacturer.product_id == product_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find(self, product_id: int, search_name: str | None) -> ProductManufacturer | None:
        stmt = select(ProductManufacturer).where(ProductManufacturer.product_id == product_id)
        if search_name is None:
            stmt = stmt.where(ProductManufacturer.search_name.is_(None))
        else:
            stmt = stmt.where(ProductManufacturer.search_name == search_name)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class VariantRepository(BaseRepository[ProductVariant]):
    model = ProductVariant

    async def get_active(self, manufacturer_id: int) -> ProductVariant | None:
        stmt = select(ProductVariant).where(
            ProductVariant.manufacturer_id == manufacturer_id,
            ProductVariant.is_active.is_(True),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def latest_version(self, manufacturer_id: int) -> ProductVariant | None:
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.manufacturer_id == manufacturer_id)
            .order_by(ProductVariant.version.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_version(self, manufacturer_id: int, version: int) -> ProductVariant | None:
        stmt = select(ProductVariant).where(
            ProductVariant.manufacturer_id == manufacturer_id,
            ProductVariant.version == version,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

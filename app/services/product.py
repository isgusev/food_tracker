"""Сервис каталога продуктов: бизнес-правила поверх репозиториев.

Роутеры не знают про ORM и SQL; сервисы не знают про HTTP.
Транзакция (commit) — на границе запроса (Unit of Work в app/db/session.py),
здесь только flush для получения id внутри одной транзакции.
"""
from __future__ import annotations


from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain import Nutrients, nutrients_are_inconsistent
from app.models.product import Brand, Product, ProductManufacturer, ProductPackage, ProductVariant
from app.repositories.product import (
    BrandRepository,
    ManufacturerRepository,
    ProductCategoryRepository,
    ProductRepository,
    VariantRepository,
)
from app.repositories.recipe import RecipeRepository
from app.schemas.product import PackageCreate, ProductCreate, ProductVariantCreate, UnitUpdate
from app.services.recipe import retarget_recipes_to_variant


class ProductService:
    def __init__(
        self,
        products: ProductRepository,
        categories: ProductCategoryRepository,
        brands: BrandRepository,
        manufacturers: ManufacturerRepository,
        variants: VariantRepository,
        recipes: RecipeRepository | None = None,
    ) -> None:
        self._products = products
        self._categories = categories
        self._brands = brands
        self._manufacturers = manufacturers
        self._variants = variants
        self._recipes = recipes

    # --- КАТЕГОРИИ ---
    async def create_category(self, name: str):
        normalized = name.strip().lower()
        if await self._categories.get_by_name_ilike(normalized):
            raise ConflictError("Такая категория уже существует")
        from app.models.product import ProductCategory

        category = ProductCategory(name=name.strip())
        self._categories.add(category)
        await self._categories.flush()
        return category

    async def list_categories(self):
        from app.models.product import ProductCategory
        from sqlalchemy import select

        return await self._categories.list(select(ProductCategory).order_by(ProductCategory.name))

    async def get_or_create_category(self, name: str) -> int:
        """Возвращает id существующей категории (без учёта регистра) или создаёт новую."""
        normalized = name.strip()
        existing = await self._categories.get_by_name_ilike(normalized.lower())
        if existing is not None:
            return existing.id
        from app.models.product import ProductCategory

        category = ProductCategory(name=normalized)
        self._categories.add(category)
        await self._categories.flush()
        return category.id

    # --- ПРОДУКТЫ ---
    async def create_product(self, data: ProductCreate) -> Product:
        category = await self._categories.get(data.category_id)
        if category is None:
            raise NotFoundError("Категория не найдена")

        brand_id = await self._resolve_brand_id(data)

        search_name = data.name.lower()
        if await self._products.find_duplicate(brand_id, search_name):
            raise ConflictError(
                f"Продукт '{data.name}' для этого бренда уже существует (регистр не имеет значения)"
            )

        product = Product(
            category_id=data.category_id,
            brand_id=brand_id,
            name=data.name,
            search_name=search_name,
        )
        self._products.add(product)
        await self._products.flush()  # получаем product.id внутри той же транзакции

        await self.create_variant(product.id, data.base_variant)
        full = await self._products.get_full(product.id)
        assert full is not None
        return full

    async def _resolve_brand_id(self, data: ProductCreate) -> int:
        if data.brand_id is not None:
            brand = await self._brands.get(data.brand_id)
            if brand is None:
                raise NotFoundError("Указанный ID бренда не найден")
            return brand.id
        assert data.brand_name is not None
        return await self.get_or_create_brand(data.brand_name)

    async def get_or_create_brand(self, brand_name: str) -> int:
        display_name = brand_name.strip()
        search_name = display_name.lower()
        existing = await self._brands.get_by_search_name(search_name)
        if existing:
            return existing.id
        brand = Brand(name=display_name, search_name=search_name)
        self._brands.add(brand)
        await self._brands.flush()
        return brand.id

    async def list_products(
        self, limit: int = 100, offset: int = 0, q: str | None = None
    ) -> list[Product]:
        return await self._products.list_full(limit=limit, offset=offset, q=q)

    async def get_product(self, product_id: int) -> Product:
        product = await self._products.get_full(product_id)
        if product is None:
            raise NotFoundError("Продукт не найден")
        return product

    # --- ЕДИНИЦЫ И УПАКОВКИ ---
    async def set_unit(self, product_id: int, data: UnitUpdate) -> Product:
        """Единица — свойство товара: меняется у всех брендов с тем же названием,
        иначе остатки разных брендов одного товара нельзя было бы сложить."""
        product = await self.get_product(product_id)
        if data.base_unit == "pcs" and not data.piece_weight_g:
            raise ValidationError("Для штучного товара укажите вес одной штуки, г")
        for p in await self._products.same_item(product.search_name):
            p.base_unit = data.base_unit
            p.piece_weight_g = data.piece_weight_g if data.base_unit == "pcs" else None
        await self._products.flush()
        return await self.get_product(product_id)

    async def add_package(self, product_id: int, data: PackageCreate) -> Product:
        product = await self.get_product(product_id)
        if any(Decimal(str(p.amount)) == data.amount for p in product.packages):
            raise ConflictError("Такая упаковка уже есть")
        product.packages.append(ProductPackage(amount=data.amount, name=data.name))
        await self._products.flush()
        return await self.get_product(product_id)

    async def delete_package(self, package_id: int) -> Product:
        package = await self._products.get_package(package_id)
        if package is None:
            raise NotFoundError("Упаковка не найдена")
        product_id = package.product_id
        await self._products.delete(package)
        await self._products.flush()
        return await self.get_product(product_id)

    # --- ВЕРСИИ КБЖУ ---
    async def get_or_create_manufacturer(
        self, product_id: int, m_name: str | None
    ) -> ProductManufacturer:
        display_name = m_name.strip() if m_name else None
        search_name = display_name.lower() if display_name else None
        existing = await self._manufacturers.find(product_id, search_name)
        if existing:
            return existing
        manufacturer = ProductManufacturer(
            product_id=product_id, name=display_name, search_name=search_name
        )
        self._manufacturers.add(manufacturer)
        await self._manufacturers.flush()
        return manufacturer

    async def create_variant(
        self, product_id: int, data: ProductVariantCreate
    ) -> ProductVariant:
        product = await self._products.get(product_id)
        if product is None:
            raise NotFoundError("Продукт не найден")

        manufacturer = await self.get_or_create_manufacturer(product_id, data.manufacturer_name)
        new_n = Nutrients(data.calories, data.proteins, data.fats, data.carbs)

        current_active = await self._variants.get_active(manufacturer.id)
        if current_active and self._same(current_active, data):
            raise ConflictError("Данные идентичны текущей активной версии")

        last = await self._variants.latest_version(manufacturer.id)
        next_version = (last.version + 1) if last else 1

        if current_active:
            current_active.is_active = False

        variant = ProductVariant(
            manufacturer_id=manufacturer.id,
            calories=data.calories,
            proteins=data.proteins,
            fats=data.fats,
            carbs=data.carbs,
            wrong_nutrients=nutrients_are_inconsistent(new_n),
            version=next_version,
            is_active=True,
        )
        self._variants.add(variant)
        await self._variants.flush()
        if current_active is not None:
            await self._retarget(current_active.id, variant.id)
        return variant

    async def _retarget(self, old_variant_id: int, new_variant_id: int) -> None:
        """Шаблоны рецептов следуют за активной версией КБЖУ (кастрюли — нет)."""
        if self._recipes is not None:
            await retarget_recipes_to_variant(
                self._recipes, self._variants, old_variant_id, new_variant_id
            )

    @staticmethod
    def _same(variant: ProductVariant, data: ProductVariantCreate) -> bool:
        return (
            variant.calories == data.calories
            and variant.proteins == data.proteins
            and variant.fats == data.fats
            and variant.carbs == data.carbs
        )

    async def rollback_version(self, product_id: int, manufacturer_id: int) -> ProductVariant:
        manufacturer = await self._manufacturers.get_for_product(manufacturer_id, product_id)
        if manufacturer is None:
            raise NotFoundError("Указанный производитель для данного продукта не найден")

        current_active = await self._variants.get_active(manufacturer_id)
        if current_active is None:
            raise NotFoundError("У этого производителя нет активной версии КБЖУ")
        if current_active.version <= 1:
            raise ValidationError(
                "Невозможно откатиться: у производителя только одна версия данных"
            )

        previous = await self._variants.get_by_version(manufacturer_id, current_active.version - 1)
        if previous is None:
            raise NotFoundError(
                f"Предыдущая версия №{current_active.version - 1} не найдена в истории"
            )

        current_active.is_active = False
        previous.is_active = True
        await self._variants.flush()
        await self._retarget(current_active.id, previous.id)
        return previous

"""Сервис каталога продуктов: бизнес-правила поверх репозиториев.

Роутеры не знают про ORM и SQL; сервисы не знают про HTTP.
Транзакция (commit) — на границе запроса (Unit of Work в app/db/session.py),
здесь только flush для получения id внутри одной транзакции.
"""
from __future__ import annotations


from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain import Nutrients, base_to_grams, grams_to_base, nutrients_are_inconsistent, quantize
from app.models.product import Brand, Product, ProductManufacturer, ProductPackage, ProductVariant
from app.repositories.product import (
    BrandRepository,
    ManufacturerRepository,
    ProductCategoryRepository,
    ProductRepository,
    VariantRepository,
)
from app.repositories.recipe import RecipeRepository
from app.schemas.product import (
    BarcodeLookup,
    BarcodeSuggestion,
    OffSearchResult,
    PackageCreate,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductWithCategoryCreate,
    UnitUpdate,
)
from app.services import barcode as off
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
        if data.barcode and await self._products.by_barcode(data.barcode):
            raise ConflictError("Продукт с таким штрихкодом уже есть в справочнике")
        if await self._products.find_duplicate(brand_id, search_name):
            raise ConflictError(
                f"Продукт '{data.name}' для этого бренда уже существует (регистр не имеет значения)"
            )

        # единица — свойство товара: новый бренд наследует её у товара с тем же названием
        same = await self._products.same_item(search_name)
        product = Product(
            category_id=data.category_id,
            brand_id=brand_id,
            name=data.name,
            search_name=search_name,
            barcode=data.barcode,
            base_unit=same[0].base_unit if same else "g",
            piece_weight_g=same[0].piece_weight_g if same else None,
        )
        self._products.add(product)
        await self._products.flush()  # получаем product.id внутри той же транзакции

        await self.create_variant(product.id, data.base_variant)
        full = await self._products.get_full(product.id)
        assert full is not None
        return full

    async def create_with_category(self, data: ProductWithCategoryCreate) -> Product:
        """Продукт из формы (или из Open Food Facts): категория по имени, штрихкод,
        упаковка с этикетки. reuse_existing — вернуть уже существующий продукт."""
        if data.reuse_existing:
            existing = await self._find_existing(data)
            if existing is not None:
                if data.barcode and not existing.barcode and await self._products.by_barcode(data.barcode) is None:
                    existing.barcode = data.barcode
                await self._add_label_package(existing, data.package_amount, data.package_unit)
                await self._products.flush()
                return await self.get_product(existing.id)
        category_id = await self.get_or_create_category(data.category_name)
        product = await self.create_product(ProductCreate(
            category_id=category_id,
            name=data.name,
            brand_name=data.brand_name or "Без бренда",
            barcode=data.barcode,
            base_variant=data.base_variant,
        ))
        await self._add_label_package(product, data.package_amount, data.package_unit, is_new=True)
        await self._products.flush()
        return await self.get_product(product.id)

    async def _find_existing(self, data: ProductWithCategoryCreate) -> Product | None:
        if data.barcode:
            found = await self._products.by_barcode(data.barcode)
            if found is not None:
                return found
        brand = await self._brands.get_by_search_name((data.brand_name or "Без бренда").strip().lower())
        if brand is None:
            return None
        dup = await self._products.find_duplicate(brand.id, data.name.lower())
        return await self._products.get_full(dup.id) if dup else None

    async def _add_label_package(
        self, product: Product, amount: Decimal | None, unit: str | None, is_new: bool = False
    ) -> None:
        """Упаковка с этикетки → в единице товара. г и мл считаем 1:1; штуки
        без веса одной штуки перевести нельзя — такую упаковку пропускаем."""
        if not amount or not unit:
            return
        if unit == "ml" and product.base_unit == "g" and is_new:
            # новый товар в бутылке — сразу учитываем в мл (если других брендов нет)
            if len(await self._products.same_item(product.search_name)) == 1:
                product.base_unit = "ml"
        if unit == "pcs":
            if product.base_unit != "pcs":
                return
            qty = amount
        else:
            if product.base_unit == "pcs" and not product.piece_weight_g:
                return
            qty = grams_to_base(amount, product.base_unit, product.piece_weight_g)
        qty = quantize(qty)
        if qty <= 0 or any(Decimal(str(p.amount)) == qty for p in product.packages):
            return
        product.packages.append(ProductPackage(amount=qty))

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

    # --- ШТРИХКОД ---
    async def lookup_barcode(self, code: str) -> BarcodeLookup:
        """Свой справочник → Open Food Facts → ничего (тогда — ввести вручную)."""
        local = await self._products.by_barcode(code)
        if local is not None:
            return BarcodeLookup(barcode=code, source="local", product=ProductResponse.model_validate(local))
        raw = await off.fetch_off(code)
        if raw is None:
            return BarcodeLookup(barcode=code, source="none")
        return BarcodeLookup(barcode=code, source="openfoodfacts", suggestion=BarcodeSuggestion(**off.parse_off(raw)))

    async def search_off(self, q: str, limit: int = 20) -> OffSearchResult:
        """Поиск по названию в Open Food Facts. Позиции, чей штрихкод уже есть
        в справочнике, возвращаются как свои продукты (local), а не подсказки."""
        raw = await off.search_off(q, limit)
        if raw is None:
            return OffSearchResult(available=False)
        items, local, seen = [], [], set()
        for p in raw:
            s = off.parse_off(p)
            if not s["name"] or (s["barcode"] and s["barcode"] in seen):
                continue
            if s["barcode"]:
                seen.add(s["barcode"])
                own = await self._products.by_barcode(s["barcode"])
                if own is not None:
                    local.append(ProductResponse.model_validate(own))
                    continue
            items.append(BarcodeSuggestion(**s))
        return OffSearchResult(items=items, local=local)

    async def set_barcode(self, product_id: int, code: str) -> Product:
        product = await self.get_product(product_id)
        other = await self._products.by_barcode(code)
        if other is not None and other.id != product.id:
            raise ConflictError(f"Этот штрихкод уже у продукта «{other.name}»")
        product.barcode = code
        await self._products.flush()
        return await self.get_product(product_id)

    # --- ЕДИНИЦЫ И УПАКОВКИ ---
    async def set_unit(self, product_id: int, data: UnitUpdate) -> Product:
        """Единица — свойство товара: меняется у всех брендов с тем же названием,
        иначе остатки разных брендов одного товара нельзя было бы сложить."""
        product = await self.get_product(product_id)
        if data.base_unit == "pcs" and not data.piece_weight_g:
            raise ValidationError("Для штучного товара укажите вес одной штуки, г")
        new_piece = data.piece_weight_g if data.base_unit == "pcs" else None
        if (product.base_unit, product.piece_weight_g) == (data.base_unit, new_piece):
            return product
        # запасы хранятся в единице товара — менять её под живыми остатками нельзя
        # (справочник общий: это задело бы и другие семьи)
        if await self._products.item_has_stock(product.search_name):
            raise ConflictError(
                "Единицу нельзя поменять, пока этот товар есть в запасах "
                "(в том числе у других семей). Сначала спишите или обнулите остаток."
            )
        for p in await self._products.same_item(product.search_name):
            # упаковки пересчитываем: старая единица → граммы → новая
            for pk in p.packages:
                g = base_to_grams(Decimal(str(pk.amount)), p.base_unit, p.piece_weight_g)
                pk.amount = quantize(grams_to_base(g, data.base_unit, new_piece))
            p.base_unit = data.base_unit
            p.piece_weight_g = new_piece
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

"""Эндпоинты каталога продуктов: тонкие HTTP-обёртки над ProductService."""
from __future__ import annotations


from fastapi import APIRouter, Query

from app.api.deps import ProductServiceDep
from app.schemas.product import (
    CategoryCreate,
    CategoryResponse,
    BarcodeIn,
    BarcodeLookup,
    OffSearchResult,
    PackageCreate,
    UnitUpdate,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductWithCategoryCreate,
)

router = APIRouter(prefix="/products", tags=["Продукты, Производители и Версии КБЖУ"])


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=201,
)
async def create_category(category: CategoryCreate, service: ProductServiceDep):
    return await service.create_category(category.name)


@router.post(
    "/with-category",
    response_model=ProductResponse,
    status_code=201,
)
async def create_product_with_category(
    product: ProductWithCategoryCreate, service: ProductServiceDep
):
    """Продукт + категория по имени (get-or-create) + упаковка с этикетки.
    reuse_existing=true — вернуть уже существующий (тот же штрихкод / название+бренд)."""
    return await service.create_with_category(product)


@router.get("/categories", response_model=list[CategoryResponse])
async def get_categories(service: ProductServiceDep):
    return await service.list_categories()


@router.post(
    "/",
    response_model=ProductResponse,
    status_code=201,
)
async def create_product(product: ProductCreate, service: ProductServiceDep):
    return await service.create_product(product)


@router.get("/", response_model=list[ProductResponse])
async def get_products(
    service: ProductServiceDep,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=100, description="Поиск по названию или бренду"),
):
    return await service.list_products(limit=limit, offset=offset, q=q)


@router.post(
    "/{product_id}/variants",
    response_model=ProductVariantResponse,
    status_code=201,
)
async def add_variant_to_product(
    product_id: int, variant_in: ProductVariantCreate, service: ProductServiceDep
):
    return await service.create_variant(product_id, variant_in)


@router.post(
    "/{product_id}/manufacturers/{manufacturer_id}/rollback",
    response_model=ProductVariantResponse,
)
async def rollback_to_previous_version(
    product_id: int, manufacturer_id: int, service: ProductServiceDep
):
    return await service.rollback_version(product_id, manufacturer_id)


@router.put("/{product_id}/unit", response_model=ProductResponse)
async def set_unit(product_id: int, payload: UnitUpdate, service: ProductServiceDep):
    """Единица учёта (г / мл / шт + вес штуки) — для всех брендов этого товара."""
    return await service.set_unit(product_id, payload)


@router.post("/{product_id}/packages", response_model=ProductResponse, status_code=201)
async def add_package(product_id: int, payload: PackageCreate, service: ProductServiceDep):
    """Типичная упаковка (в единице товара): 300 г, 930 мл, 10 шт."""
    return await service.add_package(product_id, payload)


@router.delete("/packages/{package_id}", response_model=ProductResponse)
async def delete_package(package_id: int, service: ProductServiceDep):
    return await service.delete_package(package_id)


@router.get("/off-search", response_model=OffSearchResult)
async def search_open_food_facts(
    service: ProductServiceDep,
    q: str = Query(min_length=2, max_length=100, description="Название и/или бренд"),
    limit: int = Query(default=20, ge=1, le=50),
):
    """Поиск по названию в Open Food Facts (подсказки КБЖУ, упаковки, штрихкода)."""
    return await service.search_off(q.strip(), limit)


@router.get("/barcode/{code}", response_model=BarcodeLookup)
async def lookup_barcode(code: str, service: ProductServiceDep):
    """Поиск по штрихкоду: свой справочник, затем Open Food Facts (подсказка КБЖУ)."""
    if not code.isdigit() or not 8 <= len(code) <= 14:
        from app.core.exceptions import ValidationError
        raise ValidationError("Штрихкод — 8–14 цифр")
    return await service.lookup_barcode(code)


@router.put("/{product_id}/barcode", response_model=ProductResponse)
async def set_barcode(product_id: int, payload: BarcodeIn, service: ProductServiceDep):
    """Привязать штрихкод к продукту (чтобы в следующий раз найти его сканером)."""
    return await service.set_barcode(product_id, payload.barcode)

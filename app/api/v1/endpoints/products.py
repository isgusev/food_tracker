"""Эндпоинты каталога продуктов: тонкие HTTP-обёртки над ProductService."""
from __future__ import annotations


from fastapi import APIRouter, Query

from app.api.deps import ProductServiceDep
from app.schemas.product import (
    CategoryCreate,
    CategoryResponse,
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
    """Продукт + авто-создание категории по имени (get-or-create)."""
    category_id = await service.get_or_create_category(product.category_name)
    payload = ProductCreate(
        category_id=category_id,
        name=product.name,
        brand_name=product.brand_name,
        base_variant=product.base_variant,
    )
    return await service.create_product(payload)


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

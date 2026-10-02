"""Эндпоинты каталога продуктов: тонкие HTTP-обёртки над ProductService."""

from fastapi import APIRouter, Query

from app.api.deps import ProductServiceDep
from app.schemas.product import (
    CategoryCreate,
    CategoryResponse,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductVariantResponse,
)

router = APIRouter(prefix="/products", tags=["Продукты, Производители и Версии КБЖУ"])


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=201,
)
async def create_category(category: CategoryCreate, service: ProductServiceDep):
    return await service.create_category(category.name)


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
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return await service.list_products(limit=limit, offset=offset)


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

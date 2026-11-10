"""Товары: базовые наименования без бренда, по которым идут запасы и покупки."""
from __future__ import annotations


from fastapi import APIRouter

from app.api.deps import CurrentMemberDep, ItemServiceDep, ProductServiceDep
from app.models.product import Item
from app.schemas.item import ItemMerge, ItemOut, ItemProductOut, ItemRename, ItemSuggestion, ProductItemMove

router = APIRouter(prefix="/items", tags=["Товары"])


def item_out(item: Item) -> ItemOut:
    products = sorted(item.products, key=lambda p: ((p.brand.name if p.brand else ""), p.name))
    return ItemOut(
        key=item.key, name=item.name,
        unit=products[0].base_unit if products else "g",
        products=[ItemProductOut(
            id=p.id, name=p.name, brand=p.brand.name if p.brand else None, base_unit=p.base_unit,
            packages=sorted(pk.amount for pk in p.packages),
        ) for p in products],
    )


@router.get("", response_model=list[ItemOut])
async def list_items(service: ItemServiceDep, me: CurrentMemberDep):
    """Все товары с их продуктами (справочник общий)."""
    return [item_out(i) for i in await service.all()]


@router.get("/suggestions", response_model=list[ItemSuggestion])
async def suggestions(service: ItemServiceDep, me: CurrentMemberDep):
    """Похожие товары, которые, вероятно, одно и то же («Кефир 3,2%» и «Кефир 3.2% Домик в деревне»)."""
    return [ItemSuggestion(name=name, items=[item_out(i) for i in group]) for name, group in await service.suggestions()]


@router.post("/merge", response_model=ItemOut)
async def merge(payload: ItemMerge, service: ItemServiceDep, me: CurrentMemberDep):
    """Объединить товары: продукты, запасы и настройки — в первый из списка."""
    await service.merge(payload.keys, payload.name)
    return item_out(await service.get(payload.keys[0]))


@router.patch("/{key}", response_model=ItemOut)
async def rename(key: str, payload: ItemRename, service: ItemServiceDep, me: CurrentMemberDep):
    await service.rename(key, payload.name)
    return item_out(await service.get(key))


@router.put("/products/{product_id}", response_model=ItemOut)
async def move_product(
    product_id: int, payload: ProductItemMove, service: ItemServiceDep, products: ProductServiceDep,
    me: CurrentMemberDep,
):
    """Перенести продукт в другой товар или выделить в новый."""
    product = await products.get_product(product_id)
    target = await service.move_product(product, payload.item_key, payload.new_name)
    return item_out(await service.get(target.key))

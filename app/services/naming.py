"""Как показывать продукт человеку: бренд без служебного «Без бренда», название «Творог (Простоквашино)»."""
from __future__ import annotations


NO_BRAND = "без бренда"


def brand_of(product) -> str | None:
    """Бренд для показа; служебный «Без бренда» — это отсутствие бренда."""
    name = product.brand.name if product is not None and product.brand else None
    return None if name and name.lower() == NO_BRAND else name


def display_name(variant, variant_id: int) -> str:
    """Название версии продукта для плана: «Продукт (бренд / производитель)», без «Без бренда»;
    производитель — только если отличается от бренда."""
    manufacturer = variant.manufacturer if variant is not None else None
    product = manufacturer.product if manufacturer else None
    if product is None:
        return f"Продукт #{variant_id}"
    brand_name = product.brand.name if product.brand else ""
    m_name = manufacturer.name or ""
    parts = [brand_name] + ([m_name] if m_name and m_name.lower() != brand_name.lower() else [])
    parts = [x for x in parts if x and x.lower() != NO_BRAND]
    return f"{product.name} ({' / '.join(parts)})" if parts else product.name

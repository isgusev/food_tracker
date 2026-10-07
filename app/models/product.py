"""ORM-модели каталога продуктов: категории, бренды, продукты, производители, версии КБЖУ."""
from __future__ import annotations


from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)

    products = relationship("Product", back_populates="category")


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    search_name = Column(String(255), unique=True, nullable=False)

    products = relationship("Product", back_populates="brand")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(
        Integer, ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id = Column(
        Integer, ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    name = Column(String(255), nullable=False)
    search_name = Column(String(255), nullable=False)
    is_verified = Column(Boolean, default=False)
    # Единица учёта запасов и покупок: "g" | "ml" | "pcs". КБЖУ и рецепты — всегда
    # в граммах; для штучного товара граммы переводятся через вес одной штуки,
    # для жидкостей считаем 1 мл ≈ 1 г.
    base_unit = Column(String(4), nullable=False, default="g", server_default="g")
    piece_weight_g = Column(Numeric(7, 1), nullable=True)
    # Штрихкод упаковки (EAN): один код — один продукт конкретного бренда
    barcode = Column(String(32), nullable=True, unique=True)

    category = relationship("ProductCategory", back_populates="products")
    brand = relationship("Brand", back_populates="products")
    manufacturers = relationship(
        "ProductManufacturer", back_populates="product", cascade="all, delete-orphan"
    )
    packages = relationship(
        "ProductPackage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductPackage.amount",
    )

    __table_args__ = (
        UniqueConstraint("brand_id", "search_name", name="_product_brand_search_uc"),
    )


class ProductManufacturer(Base):
    __tablename__ = "product_manufacturers"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=True, default=None)
    search_name = Column(String(255), nullable=True, default=None)

    product = relationship("Product", back_populates="manufacturers")
    variants = relationship(
        "ProductVariant", back_populates="manufacturer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("product_id", "search_name", name="_product_manufacturer_uc"),
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(
        Integer,
        ForeignKey("product_manufacturers.id", ondelete="CASCADE"),
        nullable=False,
    )
    calories = Column(Numeric(5, 1), nullable=False)
    proteins = Column(Numeric(4, 1), nullable=False)
    fats = Column(Numeric(4, 1), nullable=False)
    carbs = Column(Numeric(4, 1), nullable=False)
    wrong_nutrients = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by_user = Column(String(100), nullable=False, default="system")
    is_rejected = Column(Boolean, default=False, nullable=False)
    is_approved = Column(Boolean, default=False, nullable=False)

    manufacturer = relationship("ProductManufacturer", back_populates="variants")

    __table_args__ = (
        UniqueConstraint("manufacturer_id", "version", name="_manufacturer_version_uc"),
    )


class ProductPackage(Base):
    """Типичная упаковка продукта: «творог 300 г», «яйца 10 шт» (в базовой единице)."""

    __tablename__ = "product_packages"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount = Column(Numeric(9, 1), nullable=False)
    name = Column(String(50), nullable=True)

    product = relationship("Product", back_populates="packages")

    __table_args__ = (
        UniqueConstraint("product_id", "amount", name="_product_package_amount_uc"),
    )

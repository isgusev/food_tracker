"""Все ORM-модели приложения (единая точка импорта для Alembic и репозиториев).

Модели разбиты по доменам; здесь они пересобираются, чтобы ``Base.metadata``
содержал все таблицы при генерации миграций.
"""
from __future__ import annotations


from app.db.base import Base
from app.models.household import Household, HouseholdMember
from app.models.plan import MealItem, MealPortion
from app.models.product import (
    Brand,
    Product,
    ProductCategory,
    ProductManufacturer,
    ProductPackage,
    ProductVariant,
)
from app.models.recipe import (
    Recipe,
    RecipeActualIngredient,
    RecipeCategory,
    RecipeCookingLog,
    RecipeTemplateIngredient,
)
from app.models.stock import (
    HouseholdProduct,
    ShoppingLine,
    ShoppingList,
    StockLot,
    StockMovement,
)
from app.models.user import AuthGroup, User, UserGroup

__all__ = [
    "Base",
    "AuthGroup",
    "Brand",
    "Household",
    "HouseholdMember",
    "MealItem",
    "MealPortion",
    "Product",
    "ProductCategory",
    "ProductManufacturer",
    "ProductPackage",
    "ProductVariant",
    "Recipe",
    "RecipeActualIngredient",
    "RecipeCategory",
    "RecipeCookingLog",
    "RecipeTemplateIngredient",
    "User",
    "HouseholdProduct",
    "ShoppingLine",
    "ShoppingList",
    "StockLot",
    "StockMovement",
    "UserGroup",
]

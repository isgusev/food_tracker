"""Все ORM-модели приложения (единая точка импорта для Alembic и репозиториев).

Модели разбиты по доменам; здесь они пересобираются, чтобы ``Base.metadata``
содержал все таблицы при генерации миграций.
"""

from app.db.base import Base
from app.models.diary import DiaryLog
from app.models.product import (
    Brand,
    Product,
    ProductCategory,
    ProductManufacturer,
    ProductVariant,
)
from app.models.recipe import (
    Recipe,
    RecipeActualIngredient,
    RecipeCategory,
    RecipeCookingLog,
    RecipeTemplateIngredient,
)
from app.models.user import AuthGroup, User, UserGroup

__all__ = [
    "Base",
    "AuthGroup",
    "Brand",
    "DiaryLog",
    "Product",
    "ProductCategory",
    "ProductManufacturer",
    "ProductVariant",
    "Recipe",
    "RecipeActualIngredient",
    "RecipeCategory",
    "RecipeCookingLog",
    "RecipeTemplateIngredient",
    "User",
    "UserGroup",
]

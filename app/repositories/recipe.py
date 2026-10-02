"""Репозитории рецептов и «холодильника»."""
from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.models.product import Product, ProductManufacturer, ProductVariant
from app.models.recipe import (
    Recipe,
    RecipeActualIngredient,
    RecipeCategory,
    RecipeCookingLog,
    RecipeTemplateIngredient,
)
from app.repositories.base import BaseRepository


class RecipeCategoryRepository(BaseRepository[RecipeCategory]):
    model = RecipeCategory

    async def get_by_search_name(self, search_name: str) -> RecipeCategory | None:
        stmt = select(RecipeCategory).where(RecipeCategory.search_name == search_name)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class RecipeRepository(BaseRepository[Recipe]):
    model = Recipe

    def full_query(self):
        return select(Recipe).options(
            joinedload(Recipe.template_ingredients).joinedload(
                RecipeTemplateIngredient.variant
            ).joinedload(ProductVariant.manufacturer).joinedload(
                ProductManufacturer.product
            ).joinedload(Product.brand),
        )

    async def get_full(self, recipe_id: int) -> Recipe | None:
        stmt = self.full_query().where(Recipe.id == recipe_id)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def list_full(self, limit: int = 100, offset: int = 0) -> list[Recipe]:
        stmt = self.full_query().limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).unique().scalars().all())


class CookingLogRepository(BaseRepository[RecipeCookingLog]):
    model = RecipeCookingLog

    def full_query(self):
        return select(RecipeCookingLog).options(
            joinedload(RecipeCookingLog.actual_ingredients).joinedload(
                RecipeActualIngredient.variant
            ),
        )

    async def get_full(self, log_id: int) -> RecipeCookingLog | None:
        stmt = self.full_query().where(RecipeCookingLog.id == log_id)
        return (await self._session.execute(stmt)).unique().scalar_one_or_none()

    async def list_full(
        self, user_id: int | None = None, limit: int = 200, offset: int = 0
    ) -> list[RecipeCookingLog]:
        stmt = self.full_query()
        if user_id is not None:
            stmt = stmt.where(RecipeCookingLog.user_id == user_id)
        stmt = stmt.order_by(RecipeCookingLog.cooked_at.desc()).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).unique().scalars().all())

    async def find_active_pot(self, user_id: int, recipe_id: int) -> RecipeCookingLog | None:
        """Самая свежая недоеденная кастрюля пользователя по рецепту."""
        stmt = (
            select(RecipeCookingLog)
            .where(
                RecipeCookingLog.user_id == user_id,
                RecipeCookingLog.recipe_id == recipe_id,
                RecipeCookingLog.is_finished.is_(False),
            )
            .order_by(RecipeCookingLog.cooked_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

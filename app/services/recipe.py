"""Сервис рецептов и «холодильника» (инстансов готовки)."""
from __future__ import annotations


from decimal import Decimal

from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain import (
    ZERO,
    Nutrients,
    per_100g_from_totals,
    quantize,
)
from app.models.recipe import (
    Recipe,
    RecipeActualIngredient,
    RecipeCategory,
    RecipeCookingLog,
    RecipeTemplateIngredient,
)
from app.repositories.diary import DiaryRepository
from app.repositories.product import VariantRepository
from app.repositories.recipe import (
    CookingLogRepository,
    RecipeCategoryRepository,
    RecipeRepository,
)
from app.schemas.recipe import (
    CookingLogUpdate,
    IngredientLine,
    RecipeCookingLogCreate,
    RecipeCreate,
)


async def _sum_ingredients(
    ingredients: list[IngredientLine], variants: VariantRepository
) -> tuple[Decimal, Nutrients]:
    """Суммарный сырой вес и суммарные КБЖУ набора ингредиентов."""
    total_raw = ZERO
    totals = Nutrients(ZERO, ZERO, ZERO, ZERO)
    for ing in ingredients:
        variant = await variants.get(ing.variant_id)
        if variant is None:
            raise NotFoundError(f"Версия продукта с ID {ing.variant_id} не найдена")
        factor = ing.weight_g / Decimal("100.0")
        total_raw += ing.weight_g
        totals = Nutrients(
            calories=totals.calories + Decimal(str(variant.calories)) * factor,
            proteins=totals.proteins + Decimal(str(variant.proteins)) * factor,
            fats=totals.fats + Decimal(str(variant.fats)) * factor,
            carbs=totals.carbs + Decimal(str(variant.carbs)) * factor,
        )
    return total_raw, totals


class RecipeService:
    def __init__(
        self,
        recipes: RecipeRepository,
        categories: RecipeCategoryRepository,
        cooking_logs: CookingLogRepository,
        variants: VariantRepository,
        diary: DiaryRepository,
    ) -> None:
        self._recipes = recipes
        self._categories = categories
        self._cooking_logs = cooking_logs
        self._variants = variants
        self._diary = diary

    # --- КАТЕГОРИИ РЕЦЕПТОВ ---
    async def create_category(self, name: str) -> RecipeCategory:
        display_name = name.strip()
        search_name = display_name.lower()
        if await self._categories.get_by_search_name(search_name):
            raise ConflictError(f"Категория рецептов '{display_name}' уже существует")
        category = RecipeCategory(name=display_name, search_name=search_name)
        self._categories.add(category)
        await self._categories.flush()
        return category

    async def list_categories(self) -> list[RecipeCategory]:
        return list(
            await self._categories.list(
                select(RecipeCategory).order_by(RecipeCategory.name)
            )
        )

    # --- ШАБЛОНЫ РЕЦЕПТОВ ---
    async def create_recipe(self, data: RecipeCreate) -> Recipe:
        if await self._categories.get(data.recipe_category_id) is None:
            raise NotFoundError("Указанная категория рецептов не найдена")

        total_raw, totals = await _sum_ingredients(data.ingredients, self._variants)
        per_100 = per_100g_from_totals(totals, data.estimated_cooked_weight)

        recipe = Recipe(
            recipe_category_id=data.recipe_category_id,
            name=data.name,
            cooking_time_minutes=data.cooking_time_minutes,
            instructions=data.instructions.strip() if data.instructions else None,
            created_by_user=data.created_by_user,
            default_servings=data.default_servings,
            total_raw_weight=quantize(total_raw),
            estimated_cooked_weight=data.estimated_cooked_weight,
            calories_per_100g=quantize(per_100.calories),
            proteins_per_100g=quantize(per_100.proteins),
            fats_per_100g=quantize(per_100.fats),
            carbs_per_100g=quantize(per_100.carbs),
            template_ingredients=[
                RecipeTemplateIngredient(variant_id=i.variant_id, weight_g=i.weight_g)
                for i in data.ingredients
            ],
        )
        self._recipes.add(recipe)
        await self._recipes.flush()
        full = await self._recipes.get_full(recipe.id)
        assert full is not None
        return full

    async def list_recipes(self, limit: int = 100, offset: int = 0) -> list[Recipe]:
        return await self._recipes.list_full(limit=limit, offset=offset)

    # --- ХОЛОДИЛЬНИК ---
    async def cook(self, user_id: int, recipe_id: int, data: RecipeCookingLogCreate) -> RecipeCookingLog:
        template = await self._recipes.get(recipe_id)
        if template is None:
            raise NotFoundError("Шаблон рецепта не найден")

        total_raw, totals = await _sum_ingredients(data.ingredients, self._variants)
        per_100 = per_100g_from_totals(totals, data.total_cooked_weight)

        pot = RecipeCookingLog(
            recipe_id=recipe_id,
            user_id=user_id,
            total_raw_weight=quantize(total_raw),
            total_cooked_weight=data.total_cooked_weight,
            current_remaining_weight=data.total_cooked_weight,  # кастрюля полная
            is_finished=False,
            calories_per_100g=quantize(per_100.calories),
            proteins_per_100g=quantize(per_100.proteins),
            fats_per_100g=quantize(per_100.fats),
            carbs_per_100g=quantize(per_100.carbs),
            actual_ingredients=[
                RecipeActualIngredient(variant_id=i.variant_id, weight_g=i.weight_g)
                for i in data.ingredients
            ],
        )
        self._cooking_logs.add(pot)
        await self._cooking_logs.flush()

        # Автоуточнение планов: template_plan по этому рецепту → cooked_plan на свежую кастрюлю
        await self._diary.reattach_template_plans(user_id, recipe_id, pot.id)

        full = await self._cooking_logs.get_full(pot.id)
        assert full is not None
        return full

    async def list_pots(self, user_id: int, limit: int = 200, offset: int = 0) -> list[RecipeCookingLog]:
        return await self._cooking_logs.list_full(user_id, limit=limit, offset=offset)

    async def get_owned_pot(self, log_id: int, user_id: int) -> RecipeCookingLog:
        """Кастрюля только для её владельца; чужая = 404 (без утечки информации)."""
        pot = await self._cooking_logs.get_full(log_id)
        if pot is None or pot.user_id != user_id:
            raise NotFoundError("Запись готовки не найдена")
        return pot

    async def delete_pot(self, pot: RecipeCookingLog) -> None:
        # Связанные планы откатываются в template_plan (иначе остались бы «висячие» ссылки)
        await self._diary.detach_plans_from_pot(pot.id)
        await self._cooking_logs.delete(pot)

    async def update_pot_remainder(self, pot: RecipeCookingLog, data: CookingLogUpdate) -> RecipeCookingLog:
        remainder = data.current_remaining_weight
        if remainder > pot.total_cooked_weight:
            raise ValidationError("Остаток не может превышать общий вес готового блюда")
        pot.current_remaining_weight = remainder
        pot.is_finished = remainder <= ZERO
        await self._cooking_logs.flush()
        return pot

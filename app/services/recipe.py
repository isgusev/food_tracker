"""Сервис рецептов и «холодильника» (инстансов готовки)."""
from __future__ import annotations


from decimal import Decimal

from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain import (
    STATUS_COOKED_PLAN,
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
    CookingLogUpdateIngredients,
    IngredientLine,
    RecipeCookingLogCreate,
    RecipeCreate,
    RecipeUpdate,
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

    # --- ШАБЛОНЫ РЕЦЕПТОВ (личная библиотека пользователя) ---
    async def create_recipe(self, user_id: int, data: RecipeCreate) -> Recipe:
        if await self._categories.get(data.recipe_category_id) is None:
            raise NotFoundError("Указанная категория рецептов не найдена")
        if await self._recipes.name_exists(user_id, data.name):
            raise ConflictError(f"Рецепт '{data.name.strip()}' уже существует")

        total_raw, totals = await _sum_ingredients(data.ingredients, self._variants)
        per_100 = per_100g_from_totals(totals, data.estimated_cooked_weight)

        recipe = Recipe(
            user_id=user_id,
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
        full = await self._recipes.get_full(recipe.id, user_id=user_id)
        assert full is not None
        return full

    async def list_recipes(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> list[Recipe]:
        return await self._recipes.list_full(user_id=user_id, limit=limit, offset=offset)

    async def get_recipe(self, recipe_id: int, user_id: int) -> Recipe:
        """Чужой рецепт недоступен — единый 404 без утечки информации."""
        recipe = await self._recipes.get_full(recipe_id, user_id=user_id)
        if recipe is None:
            raise NotFoundError("Шаблон рецепта не найден")
        return recipe

    async def update_recipe(self, recipe_id: int, user_id: int, data: RecipeUpdate) -> Recipe:
        """Частичное обновление шаблона (PATCH). КБЖУ пересчитываются, если менялся состав."""
        recipe = await self._recipes.get_full(recipe_id, user_id=user_id)
        if recipe is None:
            raise NotFoundError("Шаблон рецепта не найден")

        fields = data.model_dump(exclude_unset=True)
        if "name" in fields and fields["name"].strip().lower() != recipe.name.strip().lower():
            if await self._recipes.name_exists(user_id, fields["name"]):
                raise ConflictError(f"Рецепт '{fields['name'].strip()}' уже существует")

        if "recipe_category_id" in fields and fields["recipe_category_id"] != recipe.recipe_category_id:
            if await self._categories.get(fields["recipe_category_id"]) is None:
                raise NotFoundError("Указанная категория рецептов не найдена")
            recipe.recipe_category_id = fields["recipe_category_id"]

        if "name" in fields:
            recipe.name = fields["name"]
        if "cooking_time_minutes" in fields:
            recipe.cooking_time_minutes = fields["cooking_time_minutes"]
        if "instructions" in fields:
            recipe.instructions = (
                fields["instructions"].strip() if fields["instructions"] else None
            )
        if "default_servings" in fields:
            recipe.default_servings = fields["default_servings"]

        new_weight = fields.get("estimated_cooked_weight", recipe.estimated_cooked_weight)
        if "ingredients" in fields:
            # model_dump вернул dict'ы — восстанавливаем доменные IngredientLine
            ingredient_lines = [IngredientLine(**i) for i in fields["ingredients"]]
            total_raw, totals = await _sum_ingredients(ingredient_lines, self._variants)
            recipe.total_raw_weight = quantize(total_raw)
            recipe.template_ingredients = [
                RecipeTemplateIngredient(variant_id=i.variant_id, weight_g=i.weight_g)
                for i in ingredient_lines
            ]
        else:
            # Состав не меняли — суммируем существующие строки для пересчёта на новый вес
            total_raw = sum((i.weight_g for i in recipe.template_ingredients), ZERO)
            totals = Nutrients(ZERO, ZERO, ZERO, ZERO)
            for ing in recipe.template_ingredients:
                variant = await self._variants.get(ing.variant_id)
                if variant is None:
                    raise NotFoundError(f"Версия продукта с ID {ing.variant_id} не найдена")
                factor = ing.weight_g / Decimal("100.0")
                totals = Nutrients(
                    calories=totals.calories + Decimal(str(variant.calories)) * factor,
                    proteins=totals.proteins + Decimal(str(variant.proteins)) * factor,
                    fats=totals.fats + Decimal(str(variant.fats)) * factor,
                    carbs=totals.carbs + Decimal(str(variant.carbs)) * factor,
                )

        # КБЖУ на 100 г всегда пересчитываем (мог измениться состав или вес готового)
        per_100 = per_100g_from_totals(totals, new_weight)
        recipe.estimated_cooked_weight = new_weight
        recipe.calories_per_100g = quantize(per_100.calories)
        recipe.proteins_per_100g = quantize(per_100.proteins)
        recipe.fats_per_100g = quantize(per_100.fats)
        recipe.carbs_per_100g = quantize(per_100.carbs)

        await self._recipes.flush()
        return await self.get_recipe(recipe.id, user_id)

    async def delete_recipe(self, recipe_id: int, user_id: int) -> None:
        """Удаление шаблона. Связанные кастрюли остаются (recipe_id → NULL через FK SET NULL),
        их планы в дневнике откатываются к привязке по кастрюле."""
        recipe = await self._recipes.get_full(recipe_id, user_id=user_id)
        if recipe is None:
            raise NotFoundError("Шаблон рецепта не найден")
        await self._recipes.delete(recipe)
        await self._recipes.flush()

    # --- ХОЛОДИЛЬНИК ---
    async def cook(self, user_id: int, recipe_id: int, data: RecipeCookingLogCreate) -> RecipeCookingLog:
        template = await self._recipes.get_by_id(recipe_id, user_id=user_id)
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

    async def pot_diary_usage(
        self, pot: RecipeCookingLog, today_iso: str
    ) -> dict[str, list[str]]:
        """Даты упоминания кастрюли в дневнике: past / current_future."""
        logs = await self._diary.logs_using_pot(pot.id)
        past = sorted({log.date_day for log in logs if log.date_day < today_iso})
        future = sorted({log.date_day for log in logs if log.date_day >= today_iso})
        return {"past": past, "current_future": future}

    async def delete_pot_safe(
        self, pot: RecipeCookingLog, remove_from_diary: bool, today_iso: str
    ) -> None:
        """Удаление кастрюли с учётом её использования в дневнике.

        - Есть факты/планы в ПРОШЛЫХ датах → удаление запрещено (409), чтобы
          не ломать уже учтённое питание.
        - Упоминания только в текущем/будущем → при remove_from_diary=True
          удаляем эти записи дневника; иначе кастрюля отвязывается:
          * планы остаются «надо приготовить» (template_plan по шаблону →
            попадают в план покупок);
          * съеденное остаётся в дневнике без привязки к холодильнику.
        """
        usage = await self.pot_diary_usage(pot, today_iso)
        if usage["past"]:
            raise ConflictError(
                "Кастрюлю нельзя удалить: она учтена в дневнике питания за даты: "
                + ", ".join(usage["past"])
            )
        linked = await self._diary.logs_using_pot(pot.id)
        if remove_from_diary:
            for log in linked:
                await self._diary.delete(log)
        else:
            # планы, отвязанные от кастрюли, должны остаться «планами по шаблону»
            # (иначе попадут в план покупок с нулевым весом); факты не трогаем
            for log in linked:
                if log.status == STATUS_COOKED_PLAN and log.recipe_id is None:
                    raise ValidationError(
                        "Некоторые планы не связаны с шаблоном рецепта — "
                        "удалите их вручную или подтвердите удаление из дневника."
                    )
            await self._diary.unattach_pot_keep_recipe(pot.id)
            await self._diary.detach_plans_from_pot(pot.id)
        await self._cooking_logs.delete(pot)
        await self._cooking_logs.flush()

    async def update_pot_remainder(self, pot: RecipeCookingLog, data: CookingLogUpdate) -> RecipeCookingLog:
        remainder = data.current_remaining_weight
        if remainder > pot.total_cooked_weight:
            raise ValidationError("Остаток не может превышать общий вес готового блюда")
        pot.current_remaining_weight = remainder
        pot.is_finished = remainder <= ZERO
        await self._cooking_logs.flush()
        return pot

    async def replace_pot_ingredients(
        self, pot: RecipeCookingLog, data: CookingLogUpdateIngredients
    ) -> RecipeCookingLog:
        """Полная замена фактической закладки кастрюли с пересчётом КБЖУ.

        Остаток в кастрюле остаётся прежним (вес еды мы не меняем), но его
        пищевая ценность пересчитывается по новому составу.
        """
        total_raw, totals = await _sum_ingredients(data.ingredients, self._variants)
        per_100 = per_100g_from_totals(totals, pot.total_cooked_weight)

        pot.total_raw_weight = quantize(total_raw)
        pot.actual_ingredients = [
            RecipeActualIngredient(variant_id=i.variant_id, weight_g=i.weight_g)
            for i in data.ingredients
        ]
        pot.calories_per_100g = quantize(per_100.calories)
        pot.proteins_per_100g = quantize(per_100.proteins)
        pot.fats_per_100g = quantize(per_100.fats)
        pot.carbs_per_100g = quantize(per_100.carbs)

        await self._cooking_logs.flush()
        full = await self._cooking_logs.get_full(pot.id)
        assert full is not None
        return full

"""Сервис рецептов и «холодильника» (инстансов готовки)."""
from __future__ import annotations


from datetime import date
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
from app.repositories.plan import PlanRepository
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
    PotArchiveItem,
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


def _lines(recipe: Recipe) -> list[IngredientLine]:
    """Текущий состав шаблона как доменные строки (для пересчёта КБЖУ)."""
    return [
        IngredientLine(variant_id=i.variant_id, weight_g=Decimal(str(i.weight_g)))
        for i in recipe.template_ingredients
    ]


def _apply_per_100(target, per_100: Nutrients) -> None:
    target.calories_per_100g = quantize(per_100.calories)
    target.proteins_per_100g = quantize(per_100.proteins)
    target.fats_per_100g = quantize(per_100.fats)
    target.carbs_per_100g = quantize(per_100.carbs)


async def retarget_recipes_to_variant(
    recipes: RecipeRepository,
    variants: VariantRepository,
    old_variant_id: int,
    new_variant_id: int,
) -> int:
    """Новая активная версия КБЖУ продукта → шаблоны рецептов переходят на неё.

    Шаблон описывает «что я обычно готовлю» и должен считаться по актуальной
    этикетке. Кастрюли (фактические готовки) НЕ трогаем: в них зафиксирована
    версия, по которой блюдо реально было приготовлено и съедено.
    """
    new_variant = await variants.get(new_variant_id)
    if new_variant is None:
        return 0
    affected = await recipes.list_using_variant(old_variant_id)
    for recipe in affected:
        for ing in recipe.template_ingredients:
            if ing.variant_id == old_variant_id:
                ing.variant = new_variant
        await recipes.flush()
        total_raw, totals = await _sum_ingredients(_lines(recipe), variants)
        recipe.total_raw_weight = quantize(total_raw)
        _apply_per_100(
            recipe, per_100g_from_totals(totals, Decimal(str(recipe.estimated_cooked_weight)))
        )
    await recipes.flush()
    return len(affected)


class RecipeService:
    def __init__(
        self,
        recipes: RecipeRepository,
        categories: RecipeCategoryRepository,
        cooking_logs: CookingLogRepository,
        variants: VariantRepository,
        plan: PlanRepository,
    ) -> None:
        self._recipes = recipes
        self._categories = categories
        self._cooking_logs = cooking_logs
        self._variants = variants
        self._plan = plan

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

    # --- ШАБЛОНЫ РЕЦЕПТОВ (общая библиотека семьи) ---
    async def create_recipe(self, household_id: int, user_id: int, data: RecipeCreate) -> Recipe:
        if await self._categories.get(data.recipe_category_id) is None:
            raise NotFoundError("Указанная категория рецептов не найдена")
        if await self._recipes.name_exists(household_id, data.name):
            raise ConflictError(f"Рецепт '{data.name.strip()}' уже существует")

        total_raw, totals = await _sum_ingredients(data.ingredients, self._variants)
        per_100 = per_100g_from_totals(totals, data.estimated_cooked_weight)

        recipe = Recipe(
            household_id=household_id,
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
        full = await self._recipes.get_full(recipe.id, household_id=household_id)
        assert full is not None
        return full

    async def list_recipes(
        self, household_id: int, limit: int = 100, offset: int = 0
    ) -> list[Recipe]:
        return await self._recipes.list_full(household_id=household_id, limit=limit, offset=offset)

    async def get_recipe(self, recipe_id: int, household_id: int) -> Recipe:
        """Рецепт другой семьи недоступен — единый 404 без утечки информации."""
        recipe = await self._recipes.get_full(recipe_id, household_id=household_id)
        if recipe is None:
            raise NotFoundError("Шаблон рецепта не найден")
        return recipe

    async def update_recipe(self, recipe_id: int, household_id: int, data: RecipeUpdate) -> Recipe:
        """Частичное обновление шаблона (PATCH). КБЖУ пересчитываются, если менялся состав."""
        recipe = await self._recipes.get_full(recipe_id, household_id=household_id)
        if recipe is None:
            raise NotFoundError("Шаблон рецепта не найден")

        fields = data.model_dump(exclude_unset=True)
        if "name" in fields and fields["name"].strip().lower() != recipe.name.strip().lower():
            if await self._recipes.name_exists(household_id, fields["name"]):
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
            total_raw, totals = await _sum_ingredients(_lines(recipe), self._variants)

        # КБЖУ на 100 г всегда пересчитываем (мог измениться состав или вес готового)
        recipe.estimated_cooked_weight = new_weight
        _apply_per_100(recipe, per_100g_from_totals(totals, new_weight))

        await self._recipes.flush()
        return await self.get_recipe(recipe.id, household_id)

    async def delete_recipe(self, recipe_id: int, household_id: int) -> None:
        """Удаление шаблона. Кастрюли и блюда плана остаются (recipe_id → NULL через FK)."""
        recipe = await self._recipes.get_full(recipe_id, household_id=household_id)
        if recipe is None:
            raise NotFoundError("Шаблон рецепта не найден")
        await self._recipes.delete(recipe)
        await self._recipes.flush()

    # --- ХОЛОДИЛЬНИК ---
    async def cook(
        self,
        household_id: int,
        user_id: int,
        recipe_id: int,
        data: RecipeCookingLogCreate,
        today: date,
    ) -> RecipeCookingLog:
        template = await self._recipes.get_by_id(recipe_id, household_id=household_id)
        if template is None:
            raise NotFoundError("Шаблон рецепта не найден")

        total_raw, totals = await _sum_ingredients(data.ingredients, self._variants)
        per_100 = per_100g_from_totals(totals, data.total_cooked_weight)

        pot = RecipeCookingLog(
            recipe_id=recipe_id,
            household_id=household_id,
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

        # Блюда плана по этому рецепту резервируются в свежей кастрюле —
        # начиная с сегодняшнего дня и только сколько влезает в выход блюда
        await self._plan.attach_to_new_pot(
            household_id, recipe_id, pot.id, from_date=today, capacity_g=data.total_cooked_weight
        )

        full = await self._cooking_logs.get_full(pot.id)
        assert full is not None
        return full

    async def list_pots(
        self,
        household_id: int,
        limit: int = 200,
        offset: int = 0,
        include_finished: bool = False,
    ) -> list[RecipeCookingLog]:
        return await self._cooking_logs.list_full(
            household_id, limit=limit, offset=offset, include_finished=include_finished
        )

    async def pot_plan_stats(self, household_id: int) -> dict[int, Decimal]:
        """Резерв плана по кастрюлям (для колонки «Запланировано»)."""
        return await self._plan.reserved_by_pot(household_id)

    async def get_owned_pot(self, log_id: int, household_id: int) -> RecipeCookingLog:
        """Кастрюля только своей семьи; чужая = 404 (без утечки информации)."""
        pot = await self._cooking_logs.get_full(log_id)
        if pot is None or pot.household_id != household_id:
            raise NotFoundError("Запись готовки не найдена")
        return pot

    async def pot_diary_usage(
        self, pot: RecipeCookingLog, today: date
    ) -> dict[str, list[str]]:
        """Даты, где кастрюля участвует в плане: past / current_future (ISO-строки)."""
        items = await self._plan.items_touching_pot(pot.id)
        past = sorted({i.date_day for i in items if i.date_day < today})
        future = sorted({i.date_day for i in items if i.date_day >= today})
        return {
            "past": [d.isoformat() for d in past],
            "current_future": [d.isoformat() for d in future],
        }

    async def delete_pot_safe(
        self, pot: RecipeCookingLog, remove_from_diary: bool, today: date
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
        usage = await self.pot_diary_usage(pot, today)
        if usage["past"]:
            raise ConflictError(
                "Кастрюлю нельзя удалить: она учтена в дневнике питания за даты: "
                + ", ".join(usage["past"])
            )
        linked = await self._plan.items_touching_pot(pot.id)
        if remove_from_diary:
            for item in linked:
                await self._plan.delete(item)
        else:
            # блюда без рецепта нельзя вернуть в «надо приготовить» — покупать нечего
            for item in linked:
                if item.cooking_log_id == pot.id and item.recipe_id is None:
                    raise ValidationError(
                        "Некоторые блюда плана не связаны с рецептом — "
                        "удалите их вручную или подтвердите удаление из плана."
                    )
            # несъеденное — снова «надо приготовить», съеденное остаётся без холодильника
            await self._plan.detach_from_pot(pot.id, keep_eaten_link=False)
        await self._cooking_logs.flush()
        await self._cooking_logs.delete(pot)
        await self._cooking_logs.flush()

    async def update_pot_remainder(self, pot: RecipeCookingLog, data: CookingLogUpdate) -> RecipeCookingLog:
        remainder = data.current_remaining_weight
        if remainder > pot.total_cooked_weight:
            raise ValidationError("Остаток не может превышать общий вес готового блюда")
        pot.current_remaining_weight = remainder
        pot.is_finished = remainder <= ZERO
        await self._cooking_logs.flush()
        # остатка стало меньше — поздние блюда, которым не хватает, снова «надо приготовить»
        await self._plan.release_overbooked(pot.id, remainder)
        return pot

    # --- АРХИВ ХОЛОДИЛЬНИКА ---
    async def list_pot_archive(
        self, household_id: int, include_deleted: bool, limit: int = 200, offset: int = 0
    ) -> list[PotArchiveItem]:
        """Закончившиеся кастрюли (пустые или удалённые) с логом съедания/списания.

        Удалённые физически в архиве отсутствуют; помеченные is_discarded —
        показываются с флагом «удалена», если include_deleted=True.
        """
        pots = await self._cooking_logs.list_finished(household_id, limit=limit, offset=offset)
        items: list[PotArchiveItem] = []
        for pot in pots:
            if pot.is_discarded and not include_deleted:
                continue
            recipe_name = None
            if pot.recipe_id is not None:
                recipe = await self._recipes.get_by_id(pot.recipe_id, household_id=household_id)
                recipe_name = recipe.name if recipe else None
            items.append(
                PotArchiveItem(
                    id=pot.id,
                    recipe_id=pot.recipe_id,
                    recipe_name=recipe_name,
                    cooked_at=pot.cooked_at,
                    total_cooked_weight=pot.total_cooked_weight,
                    calories_per_100g=pot.calories_per_100g,
                    events=await self._pot_events(pot),
                    is_discarded=bool(pot.is_discarded),
                )
            )
        return items

    async def _pot_events(self, pot: RecipeCookingLog) -> list[str]:
        """Человекочитаемый лог жизни кастрюли: съедено по приёмам пищи + списания."""
        items = await self._plan.items_touching_pot(pot.id)
        eaten_by_day: dict[date, Decimal] = {}
        events: list[str] = []
        for item in items:
            for portion in item.portions:
                if portion.is_eaten and portion.eaten_from_pot_id == pot.id:
                    eaten_by_day[item.date_day] = eaten_by_day.get(item.date_day, ZERO) + Decimal(
                        str(portion.weight_g)
                    )
        for day, grams in sorted(eaten_by_day.items()):
            events.append(f"{day}: съедено {quantize(grams)} г")
        consumed = sum(eaten_by_day.values(), start=ZERO)
        discarded_g = Decimal(str(pot.total_cooked_weight)) - consumed - Decimal(
            str(pot.current_remaining_weight)
        )
        if discarded_g > ZERO:
            events.append(f"списано {quantize(discarded_g)} г (гости/испортилось)")
        if pot.is_discarded:
            events.append("удалена из холодильника (остаток выброшен)")
        elif pot.is_finished:
            events.append("блюдо доедено")
        return events

    async def mark_pot_discarded(self, pot: RecipeCookingLog) -> RecipeCookingLog:
        """Пометить кастрюлю удалённой: остаток выбрасывается, запись уходит в архив.

        Физическое удаление не меняется (DELETE остаётся); здесь — мягкое
        удаление для случаев «пришли гости/испортилось», чтобы история
        сохранилась в архиве холодильника.
        """
        pot.is_discarded = True
        pot.is_finished = True
        pot.current_remaining_weight = ZERO
        # несъеденные блюда плана снова «надо приготовить» по шаблону
        await self._plan.detach_from_pot(pot.id)
        await self._cooking_logs.flush()
        full = await self._cooking_logs.get_full(pot.id)
        assert full is not None
        return full

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

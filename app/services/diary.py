"""Сервис дневника питания: планы, факты, списки покупок.

Вся «магия» КБЖУ и холодильника собрана здесь; роутер — тонкая HTTP-обёртка.
"""
from __future__ import annotations


from decimal import Decimal

from app.core.exceptions import NotFoundError, ValidationError
from app.domain import (
    STATUS_COOKED_PLAN,
    STATUS_FACT,
    STATUS_TEMPLATE_PLAN,
    Nutrients,
    quantize,
    scale_nutrients,
)
from app.models.diary import DiaryLog
from app.repositories.diary import DiaryRepository
from app.repositories.recipe import CookingLogRepository, RecipeRepository
from app.schemas.diary import (
    DiaryLogCreate,
    DiaryLogResponse,
    ShoppingListItem,
)

HUNDRED = Decimal("100.0")


class DiaryService:
    def __init__(
        self,
        diary: DiaryRepository,
        recipes: RecipeRepository,
        cooking_logs: CookingLogRepository,
    ) -> None:
        self._diary = diary
        self._recipes = recipes
        self._cooking_logs = cooking_logs

    # --- ЧТЕНИЕ ---
    async def list_for_day(self, user_id: int, date_day: str) -> list[DiaryLogResponse]:
        logs = await self._diary.list_for_day(user_id, date_day)
        return [await self._to_response(log) for log in logs]

    async def get_owned(self, log_id: int, user_id: int) -> DiaryLog:
        """Возвращает запись только её владельцу; чужая запись = 404 (без утечки)."""
        log = await self._diary.get_full(log_id)
        if log is None or log.user_id != user_id:
            raise NotFoundError("Запись в дневнике не найдена")
        return log

    async def _to_response(self, log: DiaryLog) -> DiaryLogResponse:
        res = DiaryLogResponse.model_validate(log)
        if res.recipe_name is None and log.recipe_id is not None:
            # Связь с рецептом не загружена (объект после flush/создания без
            # eager load) — подтягиваем название напрямую.
            recipe = await self._recipes.get_full(log.recipe_id)
            res.recipe_name = recipe.name if recipe else "Удаленный рецепт"
        # Источник КБЖУ: точный инстанс (кастрюля) или шаблон рецепта
        source = None
        if log.status in (STATUS_COOKED_PLAN, STATUS_FACT) and log.cooking_log_id:
            source = log.cooking_log
            if source is None:  # связь не загружена — тянем кастрюлю
                source = await self._cooking_logs.get_full(log.cooking_log_id)
        if source is None:
            source = log.recipe
            if source is None and log.recipe_id is not None:
                source = await self._recipes.get_full(log.recipe_id)

        if source is not None:
            per_100 = Nutrients(
                calories=Decimal(str(source.calories_per_100g)),
                proteins=Decimal(str(source.proteins_per_100g)),
                fats=Decimal(str(source.fats_per_100g)),
                carbs=Decimal(str(source.carbs_per_100g)),
            )
            scaled = scale_nutrients(per_100, log.weight_g)
            res.calories = quantize(scaled.calories)
            res.proteins = quantize(scaled.proteins)
            res.fats = quantize(scaled.fats)
            res.carbs = quantize(scaled.carbs)
        return res

    # --- СОЗДАНИЕ ПЛАНА ---
    async def add_plan(self, user_id: int, data: DiaryLogCreate) -> DiaryLogResponse:
        recipe = await self._recipes.get_by_id(data.recipe_id, user_id=user_id)
        if recipe is None:
            raise NotFoundError("Рецепт не найден")

        log = DiaryLog(
            user_id=user_id,
            date_day=data.date_day,
            meal_type=data.meal_type,
            status=STATUS_TEMPLATE_PLAN,
            recipe_id=data.recipe_id,
            weight_g=data.weight_g,
            servings_multiplier=data.servings_multiplier,
            scale_all_proportions=data.servings_multiplier < 0,
        )
        self._diary.add(log)
        await self._diary.flush()
        return await self._to_response(log)

    # --- ОБНОВЛЕНИЕ ВЕСА ---
    async def update_weight(
        self, log: DiaryLog, new_weight: Decimal
    ) -> DiaryLogResponse:
        """Меняет вес порции, не переключая статус; для факта синхронизирует кастрюлю."""
        if log.status == STATUS_FACT and log.cooking_log_id:
            pot = await self._cooking_logs.get(log.cooking_log_id)
            if pot is not None:
                # Возвращаем старый вес в кастрюлю и вычитаем новый
                remainder = pot.current_remaining_weight + log.weight_g - new_weight
                pot.current_remaining_weight = max(remainder, Decimal("0"))
                pot.is_finished = pot.current_remaining_weight <= Decimal("0")

        log.weight_g = new_weight
        await self._diary.flush()
        return await self._to_response(log)

    # --- «СЪЕДЕНО» ---
    async def mark_eaten(self, log: DiaryLog, new_weight: Decimal) -> DiaryLogResponse:
        """План → факт (или правка веса уже съеденного); списывает вес из кастрюли."""
        # Если запись висела без кастрюли — привязываем активную по её рецепту.
        # Иначе (даже для template_plan!) считаем КБЖУ по шаблону рецепта:
        # «съел» можно и то, что готовил без записи в холодильник.
        if log.cooking_log_id is None and log.recipe_id is not None:
            pot = await self._cooking_logs.find_active_pot(log.user_id, log.recipe_id)
            if pot is not None:
                log.cooking_log_id = pot.id
                if log.status == STATUS_TEMPLATE_PLAN:
                    log.status = STATUS_COOKED_PLAN

        was_fact = log.status == STATUS_FACT
        if log.cooking_log_id is not None:
            pot = await self._cooking_logs.get(log.cooking_log_id)
            if pot is not None:
                remainder = pot.current_remaining_weight
                if was_fact:
                    remainder += log.weight_g  # откат предыдущего фактического веса
                remainder -= new_weight
                if remainder < Decimal("0"):
                    raise ValidationError(
                        f"Недостаточно еды в холодильнике: осталось {pot.current_remaining_weight} г, "
                        f"требуется {new_weight} г"
                    )
                pot.current_remaining_weight = remainder
                pot.is_finished = remainder <= Decimal("0")

        log.weight_g = new_weight
        log.status = STATUS_FACT
        await self._diary.flush()
        return log

    # --- УДАЛЕНИЕ ---
    async def delete(self, log: DiaryLog) -> None:
        # Факт удаляем — возвращаем вес в кастрюлю, иначе холодильник «врёт»
        if log.status == STATUS_FACT and log.cooking_log_id is not None:
            pot = await self._cooking_logs.get(log.cooking_log_id)
            if pot is not None:
                pot.current_remaining_weight += log.weight_g
                pot.is_finished = False
        await self._diary.delete(log)

    # --- СПИСОК ПОКУПОК ---
    async def shopping_list(
        self, user_id: int, start_date: str, end_date: str
    ) -> list[ShoppingListItem]:
        """Агрегированная закупка по планам (template_plan) за диапазон дат."""
        plans = await self._diary.list_planned_in_range(user_id, start_date, end_date)

        cart: dict[int, dict] = {}
        for meal in plans:
            recipe = meal.recipe
            if recipe is None:
                continue
            # Рецепт с ингредиентами подгружаем явно (в full_query их нет)
            recipe_full = await self._recipes.get_full(recipe.id)
            if recipe_full is None:
                continue

            base_servings = Decimal(recipe_full.default_servings or 1)
            estimated_weight = Decimal(str(recipe_full.estimated_cooked_weight))
            if estimated_weight <= 0:
                continue
            single_portion_weight = estimated_weight / base_servings

            # Восстанавливаем долю пользователя (например, 120г / 100г = 1.2)
            user_ratio = Decimal(str(meal.weight_g)) / single_portion_weight

            raw_multiplier = int(meal.servings_multiplier or 1)
            scale_all = raw_multiplier < 0 or bool(meal.scale_all_proportions)
            total_people = Decimal(abs(raw_multiplier)) or Decimal(1)

            if total_people > 1:
                if scale_all:
                    family_portions = user_ratio * total_people
                else:
                    family_portions = user_ratio + (total_people - Decimal(1))
            else:
                family_portions = user_ratio

            scale_factor = family_portions / base_servings

            for ing in recipe_full.template_ingredients:
                needed = Decimal(str(ing.weight_g)) * scale_factor
                variant = ing.variant
                name = self._display_name(variant, ing.variant_id)
                entry = cart.setdefault(ing.variant_id, {"name": name, "weight": Decimal("0")})
                entry["weight"] += needed

        return [
            ShoppingListItem(
                variant_id=vid,
                product_name=item["name"],
                weight_g=quantize(item["weight"]),
            )
            for vid, item in sorted(cart.items())
        ]

    @staticmethod
    def _display_name(variant, variant_id: int) -> str:
        if variant is None:
            return f"Продукт #{variant_id}"
        manufacturer = variant.manufacturer
        product = manufacturer.product if manufacturer else None
        if product is None:
            return f"Продукт #{variant_id}"
        brand_name = product.brand.name if product.brand else ""
        m_name = manufacturer.name or ""
        display = f"{product.name} ({brand_name} / {m_name})".replace("( / )", "").strip()
        return display

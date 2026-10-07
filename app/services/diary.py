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
from app.repositories.product import VariantRepository
from app.repositories.recipe import CookingLogRepository, RecipeRepository
from app.schemas.diary import (
    DiaryLogCreate,
    DiaryLogResponse,
    PotSourceStatus,
    ShoppingListItem,
)

HUNDRED = Decimal("100.0")


class DiaryService:
    def __init__(
        self,
        diary: DiaryRepository,
        recipes: RecipeRepository,
        cooking_logs: CookingLogRepository,
        variants: VariantRepository,
    ) -> None:
        self._diary = diary
        self._recipes = recipes
        self._cooking_logs = cooking_logs
        self._variants = variants

    # --- ЧТЕНИЕ ---
    async def list_for_day(self, user_id: int, date_day: str) -> list[DiaryLogResponse]:
        logs = await self._diary.list_for_day(user_id, date_day)
        return [await self._to_response(log) for log in logs]

    async def list_for_range(
        self, user_id: int, start_date: str, end_date: str
    ) -> list[DiaryLogResponse]:
        logs = await self._diary.list_in_range(user_id, start_date, end_date)
        return [await self._to_response(log) for log in logs]

    async def get_owned(self, log_id: int, user_id: int) -> DiaryLog:
        """Возвращает запись только её владельцу; чужая запись = 404 (без утечки)."""
        log = await self._diary.get_full(log_id)
        if log is None or log.user_id != user_id:
            raise NotFoundError("Запись в дневнике не найдена")
        return log

    # --- ИНФОСТАТУС ИСТОЧНИКА БЛЮДА (холодильник) ---
    async def _fill_source_status(
        self, log: DiaryLog, res: DiaryLogResponse
    ) -> None:
        """Наполняет поля source_status/fridge_* для отображения в UI.

        - cooked_plan / fact с кастрюлей → источник «из холодильника» (статус
          уже задан привязкой; показываем остаток и резерв этой кастрюли);
        - template_plan → активная кастрюля по рецепту, если есть («хватает ли»
          на эту порцию с учётом уже зарезервированных планов), иначе
          «Не приготовлено»;
        - fact без кастрюли → «detached» (было съедено без холодильника);
        - готовый продукт → «product» (холодильник блюд не участвует).
        """
        if log.variant_id is not None:
            res.source_status = "product"
            return
        if log.status == STATUS_FACT and log.cooking_log_id is None:
            res.source_status = "detached"
            return
        if log.cooking_log_id is not None:
            pot = log.cooking_log
            if pot is None:
                pot = await self._cooking_logs.get(log.cooking_log_id)
            if pot is not None and not pot.is_discarded:
                res.source_status = "fridge"
                res.fridge_pot_id = pot.id
                res.fridge_available_g = Decimal(str(pot.current_remaining_weight))
                planned = await self._diary.planned_weight_by_pot(log.user_id)
                res.fridge_planned_g = planned.get(pot.id, Decimal("0"))
                res.fridge_enough = res.fridge_available_g >= log.weight_g
                return
        if log.recipe_id is not None:
            pot = await self._cooking_logs.find_active_pot(log.user_id, log.recipe_id)
            if pot is not None:
                res.source_status = "not_cooked"  # есть кастрюля, но план не привязан
                res.fridge_pot_id = pot.id
                res.fridge_available_g = Decimal(str(pot.current_remaining_weight))
                planned = await self._diary.planned_weight_by_pot(log.user_id)
                res.fridge_planned_g = planned.get(pot.id, Decimal("0"))
                res.fridge_enough = res.fridge_available_g >= log.weight_g
            else:
                res.source_status = "not_cooked"

    async def pot_status_for_recipe(
        self, user_id: int, recipe_id: int, portion_g: Decimal | None = None
    ) -> PotSourceStatus:
        """Активная кастрюля рецепта + сколько в ней свободно (для формы планирования)."""
        pot = await self._cooking_logs.find_active_pot(user_id, recipe_id)
        if pot is None:
            return PotSourceStatus(has_active_pot=False)
        planned = await self._diary.planned_weight_by_pot(user_id)
        reserved = planned.get(pot.id, Decimal("0"))
        available = Decimal(str(pot.current_remaining_weight))
        enough = (available >= portion_g) if portion_g is not None else None
        return PotSourceStatus(
            has_active_pot=True,
            pot_id=pot.id,
            available_g=available,
            planned_g=reserved,
            enough_for_portion=enough,
        )

    async def _to_response(self, log: DiaryLog) -> DiaryLogResponse:
        res = DiaryLogResponse.model_validate(log)
        if log.variant_id is not None:
            return await self._product_response(log, res)
        if res.recipe_name is None and log.recipe_id is not None:
            # Связь с рецептом не загружена (объект после flush/создания без
            # eager load) — подтягиваем название напрямую.
            recipe = await self._recipes.get_full(log.recipe_id)
            res.recipe_name = recipe.name if recipe else "Удаленный рецепт"

        # Инфостатус источника блюда для UI («откуда берём», хватает ли в холодильнике)
        await self._fill_source_status(log, res)

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

    async def _product_response(
        self, log: DiaryLog, res: DiaryLogResponse
    ) -> DiaryLogResponse:
        """Запись «готовый продукт»: КБЖУ из версии продукта, без холодильника."""
        res.kind = "product"
        res.source_status = "product"
        variant = await self._diary.get_variant_full(log.variant_id)
        if variant is None:
            res.product_name = f"Продукт #{log.variant_id}"
            return res
        res.product_name = self._display_name(variant, log.variant_id)
        per_100 = Nutrients(
            calories=Decimal(str(variant.calories)),
            proteins=Decimal(str(variant.proteins)),
            fats=Decimal(str(variant.fats)),
            carbs=Decimal(str(variant.carbs)),
        )
        scaled = scale_nutrients(per_100, Decimal(str(log.weight_g)))
        res.calories = quantize(scaled.calories)
        res.proteins = quantize(scaled.proteins)
        res.fats = quantize(scaled.fats)
        res.carbs = quantize(scaled.carbs)
        return res

    # --- СОЗДАНИЕ ПЛАНА ---
    async def add_plan(self, user_id: int, data: DiaryLogCreate) -> DiaryLogResponse:
        if data.variant_id is not None:
            if await self._variants.get(data.variant_id) is None:
                raise NotFoundError("Продукт (версия КБЖУ) не найден")
        else:
            recipe = await self._recipes.get_by_id(data.recipe_id, user_id=user_id)
            if recipe is None:
                raise NotFoundError("Рецепт не найден")

        log = DiaryLog(
            user_id=user_id,
            date_day=data.date_day,
            meal_type=data.meal_type,
            status=STATUS_TEMPLATE_PLAN,
            recipe_id=data.recipe_id,
            variant_id=data.variant_id,
            weight_g=data.weight_g,
            servings_multiplier=data.servings_multiplier,
            scale_all_proportions=False,
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

    # --- «СЪЕДЕНО» (идемпотентно: кнопка не должна срабатывать повторно) ---
    async def mark_eaten(self, log: DiaryLog, new_weight: Decimal) -> DiaryLogResponse:
        """План → факт (или правка веса уже съеденного); списывает вес из кастрюли.

        Повторный вызов для уже «съеденной» записи НЕ списывает вес повторно —
        только обновляет вес (это лечит баг двойного нажатия кнопки в UI).
        """
        already_fact = log.status == STATUS_FACT

        # Если запись висела без кастрюли — привязываем активную по её рецепту.
        # Иначе (даже для template_plan!) считаем КБЖУ по шаблону рецепта:
        # «съел» можно и то, что готовил без записи в холодильнике.
        if not already_fact and log.cooking_log_id is None and log.recipe_id is not None:
            pot = await self._cooking_logs.find_active_pot(log.user_id, log.recipe_id)
            if pot is not None:
                log.cooking_log_id = pot.id
                if log.status == STATUS_TEMPLATE_PLAN:
                    log.status = STATUS_COOKED_PLAN

        was_fact = already_fact
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
        return await self._to_response(log)

    # --- «БЫЛО БЕЗ ХОЛОДИЛЬНИКА»: отвязать факт от кастрюли ---
    async def detach_from_fridge(self, log: DiaryLog) -> DiaryLogResponse:
        """Факт остаётся в дневнике, но перестаёт быть связанным с холодильником.

        Обязательность учёта в холодильнике снимается; вес обратно в кастрюлю
        НЕ возвращается (еда реально съедена).
        """
        if log.status != STATUS_FACT:
            raise ValidationError("Отвязать от холодильника можно только съеденное")
        log.cooking_log_id = None
        await self._diary.flush()
        return await self._to_response(log)

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

        def put(variant_id: int, variant, grams: Decimal) -> None:
            entry = cart.setdefault(
                variant_id,
                {
                    "name": self._display_name(variant, variant_id),
                    "category": self._category_name(variant),
                    "weight": Decimal("0"),
                },
            )
            entry["weight"] += grams

        for meal in plans:
            # Готовый продукт: покупаем «как есть» — порция × количество человек
            if meal.variant_id is not None:
                people = Decimal(abs(int(meal.servings_multiplier or 1))) or Decimal(1)
                put(meal.variant_id, meal.variant, Decimal(str(meal.weight_g)) * people)
                continue

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
                put(ing.variant_id, ing.variant, Decimal(str(ing.weight_g)) * scale_factor)

        return [
            ShoppingListItem(
                variant_id=vid,
                product_name=item["name"],
                category_name=item["category"],
                weight_g=quantize(item["weight"]),
            )
            for vid, item in sorted(
                cart.items(), key=lambda kv: (kv[1]["category"] or "", kv[1]["name"])
            )
        ]

    @staticmethod
    def _category_name(variant) -> str | None:
        manufacturer = variant.manufacturer if variant is not None else None
        product = manufacturer.product if manufacturer else None
        category = product.category if product else None
        return category.name if category else None

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

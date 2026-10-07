"""Сервис плана питания семьи: блюда, порции по людям, холодильник, покупки.

Правила учёта:
- блюдо в плане принадлежит семье, у каждого едока своя порция;
- личные КБЖУ = порции конкретного члена семьи (гости — без личного учёта);
- кастрюля резервирует несъеденные порции привязанных блюд и списывается
  порциями при «съедено»;
- список покупок = несъеденные порции блюд без кастрюли (рецепт раскладывается
  на ингредиенты, готовый продукт покупается как есть).
"""
from __future__ import annotations


from datetime import date, datetime, timezone
from decimal import Decimal

from app.core.exceptions import NotFoundError, ValidationError
from app.domain import (
    ITEM_IN_FRIDGE,
    ITEM_PRODUCT,
    ITEM_TO_COOK,
    Nutrients,
    quantize,
    scale_nutrients,
)
from app.models.plan import MealItem, MealPortion
from app.models.recipe import RecipeCookingLog
from app.repositories.household import MemberRepository
from app.repositories.plan import PlanRepository, remaining_weight
from app.repositories.product import VariantRepository
from app.repositories.recipe import CookingLogRepository, RecipeRepository
from app.schemas.plan import (
    MealItemCreate,
    MealItemMove,
    MealItemResponse,
    PortionIn,
    PortionResponse,
    PotSourceStatus,
    ShoppingListItem,
)

ZERO = Decimal("0")


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _per_100(source) -> Nutrients:
    """КБЖУ на 100 г из рецепта/кастрюли (*_per_100g) или версии продукта."""
    if hasattr(source, "calories_per_100g"):
        return Nutrients(
            _d(source.calories_per_100g),
            _d(source.proteins_per_100g),
            _d(source.fats_per_100g),
            _d(source.carbs_per_100g),
        )
    return Nutrients(_d(source.calories), _d(source.proteins), _d(source.fats), _d(source.carbs))


def display_name(variant, variant_id: int) -> str:
    manufacturer = variant.manufacturer if variant is not None else None
    product = manufacturer.product if manufacturer else None
    if product is None:
        return f"Продукт #{variant_id}"
    brand_name = product.brand.name if product.brand else ""
    m_name = manufacturer.name or ""
    return f"{product.name} ({brand_name} / {m_name})".replace("( / )", "").strip()


def category_name(variant) -> str | None:
    manufacturer = variant.manufacturer if variant is not None else None
    product = manufacturer.product if manufacturer else None
    category = product.category if product else None
    return category.name if category else None


class PlanService:
    def __init__(
        self,
        plan: PlanRepository,
        recipes: RecipeRepository,
        cooking_logs: CookingLogRepository,
        variants: VariantRepository,
        members: MemberRepository,
    ) -> None:
        self._plan = plan
        self._recipes = recipes
        self._cooking_logs = cooking_logs
        self._variants = variants
        self._members = members

    # ------------------------------------------------------------------ чтение
    async def list_range(self, household_id: int, start: date, end: date) -> list[MealItemResponse]:
        if start > end:
            raise ValidationError("Дата окончания не может быть раньше даты начала")
        items = await self._plan.list_in_range(household_id, start, end)
        reserved = await self._plan.reserved_by_pot(household_id) if items else {}
        pots: dict[int, RecipeCookingLog | None] = {}
        return [await self._to_response(i, reserved, pots) for i in items]

    async def get_owned_item(self, item_id: int, household_id: int) -> MealItem:
        item = await self._plan.get_full(item_id)
        if item is None or item.household_id != household_id:
            raise NotFoundError("Блюдо в плане не найдено")
        return item

    async def get_owned_portion(
        self, portion_id: int, household_id: int
    ) -> tuple[MealItem, MealPortion]:
        portion = await self._plan.get_portion(portion_id)
        if portion is None:
            raise NotFoundError("Порция не найдена")
        item = await self.get_owned_item(portion.meal_item_id, household_id)
        portion = next(p for p in item.portions if p.id == portion_id)
        return item, portion

    async def response(self, item_id: int) -> MealItemResponse:
        item = await self._plan.get_full(item_id)
        reserved = await self._plan.reserved_by_pot(item.household_id)
        return await self._to_response(item, reserved, {})

    async def _pot(self, pot_id: int | None, cache: dict) -> RecipeCookingLog | None:
        if pot_id is None:
            return None
        if pot_id not in cache:
            cache[pot_id] = await self._cooking_logs.get(pot_id)
        return cache[pot_id]

    async def _to_response(
        self, item: MealItem, reserved: dict[int, Decimal], pots: dict
    ) -> MealItemResponse:
        kind = "product" if item.variant_id is not None else "recipe"
        if kind == "product":
            name = display_name(item.variant, item.variant_id)
            state = ITEM_PRODUCT
        else:
            name = item.recipe.name if item.recipe else "Удалённый рецепт"
            state = ITEM_IN_FRIDGE if item.cooking_log_id else ITEM_TO_COOK

        attached = await self._pot(item.cooking_log_id, pots)
        portions: list[PortionResponse] = []
        for p in item.portions:
            # КБЖУ: съеденное из кастрюли — по ней; иначе привязанная кастрюля,
            # иначе шаблон рецепта; для продукта — его версия КБЖУ
            if kind == "product":
                source = item.variant
            else:
                source = await self._pot(p.eaten_from_pot_id, pots) if p.is_eaten else None
                source = source or attached or item.recipe
            res = PortionResponse(
                id=p.id,
                member_id=p.member_id,
                member_name=p.member.name if p.member is not None else None,
                weight_g=_d(p.weight_g),
                is_eaten=p.is_eaten,
                eaten_from_pot_id=p.eaten_from_pot_id,
            )
            if source is not None:
                n = scale_nutrients(_per_100(source), _d(p.weight_g))
                res.calories, res.proteins = quantize(n.calories), quantize(n.proteins)
                res.fats, res.carbs = quantize(n.fats), quantize(n.carbs)
            portions.append(res)

        resp = MealItemResponse(
            id=item.id,
            date_day=item.date_day,
            meal_type=item.meal_type,
            kind=kind,
            recipe_id=item.recipe_id,
            variant_id=item.variant_id,
            name=name,
            state=state,
            cooking_log_id=item.cooking_log_id,
            portions=portions,
            total_weight_g=sum((_d(p.weight_g) for p in item.portions), ZERO),
            remaining_weight_g=remaining_weight(item),
        )
        if kind == "recipe":
            pot = attached
            if pot is None and item.recipe_id is not None:
                pot = await self._cooking_logs.find_active_pot(item.household_id, item.recipe_id)
            if pot is not None and not pot.is_discarded:
                available = _d(pot.current_remaining_weight)
                booked = reserved.get(pot.id, ZERO)
                resp.fridge_pot_id = pot.id
                resp.fridge_available_g = available
                resp.fridge_reserved_g = booked
                need = resp.remaining_weight_g
                # привязанное блюдо уже внутри резерва; непривязанному нужно свободное место
                resp.fridge_enough = (
                    available >= booked if attached else available - booked >= need
                )
        return resp

    # ------------------------------------------------------------ планирование
    async def _validate_members(self, household_id: int, portions: list[PortionIn]) -> None:
        for p in portions:
            if p.member_id is None:
                continue
            member = await self._members.get(p.member_id)
            if member is None or member.household_id != household_id:
                raise NotFoundError(f"Член семьи #{p.member_id} не найден")

    async def create(self, household_id: int, user_id: int, data: MealItemCreate) -> MealItemResponse:
        if data.variant_id is not None:
            if await self._variants.get(data.variant_id) is None:
                raise NotFoundError("Продукт (версия КБЖУ) не найден")
        elif await self._recipes.get_by_id(data.recipe_id, household_id=household_id) is None:
            raise NotFoundError("Рецепт не найден")
        await self._validate_members(household_id, data.portions)

        item = MealItem(
            household_id=household_id,
            date_day=data.date_day,
            meal_type=data.meal_type,
            recipe_id=data.recipe_id,
            variant_id=data.variant_id,
            created_by_user_id=user_id,
            portions=[MealPortion(member_id=p.member_id, weight_g=p.weight_g) for p in data.portions],
        )
        # Блюдо уже в холодильнике и свободного хватает на всех — резервируем сразу,
        # иначе оно ушло бы в покупки как «надо приготовить»
        if data.recipe_id is not None:
            pot = await self._cooking_logs.find_active_pot(household_id, data.recipe_id)
            if pot is not None:
                booked = (await self._plan.reserved_by_pot(household_id)).get(pot.id, ZERO)
                need = sum((p.weight_g for p in data.portions), ZERO)
                if _d(pot.current_remaining_weight) - booked >= need:
                    item.cooking_log_id = pot.id
        self._plan.add(item)
        await self._plan.flush()
        return await self.response(item.id)

    async def move(self, item: MealItem, data: MealItemMove) -> MealItemResponse:
        if data.date_day is not None:
            item.date_day = data.date_day
        if data.meal_type is not None:
            item.meal_type = data.meal_type
        await self._plan.flush()
        return await self.response(item.id)

    async def delete_item(self, item: MealItem) -> None:
        """Удалить блюдо: съеденное из кастрюли возвращается в неё."""
        for p in item.portions:
            await self._return_to_pot(p)
        await self._plan.delete(item)
        await self._plan.flush()

    async def add_portion(self, item: MealItem, data: PortionIn) -> MealItemResponse:
        await self._validate_members(item.household_id, [data])
        if data.member_id is not None and any(p.member_id == data.member_id for p in item.portions):
            raise ValidationError("У этого члена семьи уже есть порция в блюде")
        item.portions.append(MealPortion(member_id=data.member_id, weight_g=data.weight_g))
        await self._plan.flush()
        await self._release(item.cooking_log_id)
        return await self.response(item.id)

    async def update_portion(
        self, item: MealItem, portion: MealPortion, weight: Decimal
    ) -> MealItemResponse:
        """Новый вес порции. У съеденного из кастрюли — пересписание остатка
        (ошибка, если еды не хватает, а не молчаливое обнуление)."""
        if portion.is_eaten and portion.eaten_from_pot_id:
            pot = await self._cooking_logs.get(portion.eaten_from_pot_id)
            if pot is not None:
                remainder = _d(pot.current_remaining_weight) + _d(portion.weight_g) - weight
                if remainder < ZERO:
                    raise ValidationError(
                        f"Недостаточно еды в холодильнике: осталось {pot.current_remaining_weight} г"
                    )
                self._set_remaining(pot, remainder)
        portion.weight_g = weight
        await self._plan.flush()
        await self._release(portion.eaten_from_pot_id)
        await self._release(item.cooking_log_id)
        return await self.response(item.id)

    async def delete_portion(self, item: MealItem, portion: MealPortion) -> MealItemResponse | None:
        """Убрать порцию; последняя порция — блюдо удаляется целиком (вернётся None)."""
        if len(item.portions) == 1:
            await self.delete_item(item)
            return None
        await self._return_to_pot(portion)
        item.portions.remove(portion)
        await self._plan.flush()
        return await self.response(item.id)

    # ----------------------------------------------------------------- съедено
    async def eat_portion(
        self, item: MealItem, portion: MealPortion, weight: Decimal | None
    ) -> MealItemResponse:
        weight = weight if weight is not None else _d(portion.weight_g)
        if portion.is_eaten:
            return await self.update_portion(item, portion, weight)
        await self._eat(item, [(portion, weight)])
        return await self.response(item.id)

    async def eat_all(self, item: MealItem) -> MealItemResponse:
        """«Все поели»: несъеденные порции → съедено с плановым весом."""
        todo = [(p, _d(p.weight_g)) for p in item.portions if not p.is_eaten]
        if not todo:
            raise ValidationError("Все порции уже отмечены как съеденные")
        await self._eat(item, todo)
        return await self.response(item.id)

    async def _eat(self, item: MealItem, todo: list[tuple[MealPortion, Decimal]]) -> None:
        pot = await self._cooking_logs.get(item.cooking_log_id) if item.cooking_log_id else None
        if pot is None and item.recipe_id is not None:
            # ели блюдо, которое есть в холодильнике, но план не был к нему привязан
            pot = await self._cooking_logs.find_active_pot(item.household_id, item.recipe_id)
            if pot is not None:
                item.cooking_log_id = pot.id
        need = sum((w for _, w in todo), ZERO)
        if pot is not None:
            remainder = _d(pot.current_remaining_weight) - need
            if remainder < ZERO:
                raise ValidationError(
                    f"Недостаточно еды в холодильнике: осталось {pot.current_remaining_weight} г, "
                    f"требуется {quantize(need)} г"
                )
            self._set_remaining(pot, remainder)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for portion, weight in todo:
            portion.weight_g = weight
            portion.is_eaten = True
            portion.eaten_at = now
            portion.eaten_from_pot_id = pot.id if pot is not None else None
        await self._plan.flush()
        if pot is not None:
            # съели больше плана — поздним блюдам может уже не хватить
            await self._release(pot.id)

    async def uneat_portion(self, item: MealItem, portion: MealPortion) -> MealItemResponse:
        """Отменить «съедено»: вес возвращается в кастрюлю, порция снова в плане."""
        if not portion.is_eaten:
            raise ValidationError("Порция ещё не отмечена как съеденная")
        await self._return_to_pot(portion)
        portion.is_eaten = False
        portion.eaten_at = None
        portion.eaten_from_pot_id = None
        await self._plan.flush()
        await self._release(item.cooking_log_id)
        return await self.response(item.id)

    async def detach_portion(self, item: MealItem, portion: MealPortion) -> MealItemResponse:
        """«Ели не из холодильника»: съеденное отвязывается от кастрюли, вес в неё не возвращается."""
        if not portion.is_eaten:
            raise ValidationError("Отвязать от холодильника можно только съеденное")
        portion.eaten_from_pot_id = None
        await self._plan.flush()
        return await self.response(item.id)

    # ------------------------------------------------------------- кастрюля
    @staticmethod
    def _set_remaining(pot: RecipeCookingLog, remainder: Decimal) -> None:
        pot.current_remaining_weight = remainder
        pot.is_finished = remainder <= ZERO

    async def _return_to_pot(self, portion: MealPortion) -> None:
        if portion.is_eaten and portion.eaten_from_pot_id:
            pot = await self._cooking_logs.get(portion.eaten_from_pot_id)
            if pot is not None and not pot.is_discarded:
                self._set_remaining(pot, _d(pot.current_remaining_weight) + _d(portion.weight_g))

    async def _release(self, pot_id: int | None) -> None:
        if pot_id is None:
            return
        pot = await self._cooking_logs.get(pot_id)
        if pot is not None:
            await self._plan.release_overbooked(pot.id, _d(pot.current_remaining_weight))

    async def pot_status(
        self, household_id: int, recipe_id: int, portion_g: Decimal | None
    ) -> PotSourceStatus:
        """Есть ли активная кастрюля рецепта и сколько в ней свободно (для формы планирования)."""
        pot = await self._cooking_logs.find_active_pot(household_id, recipe_id)
        if pot is None:
            return PotSourceStatus(has_active_pot=False)
        booked = (await self._plan.reserved_by_pot(household_id)).get(pot.id, ZERO)
        available = _d(pot.current_remaining_weight)
        return PotSourceStatus(
            has_active_pot=True,
            pot_id=pot.id,
            available_g=available,
            planned_g=booked,
            enough_for_portion=(available - booked >= portion_g) if portion_g is not None else None,
        )

    # ---------------------------------------------------------------- покупки
    async def shopping_list(self, household_id: int, start: date, end: date) -> list[ShoppingListItem]:
        """Несъеденные порции блюд без кастрюли: рецепты → ингредиенты, продукты — как есть."""
        if start > end:
            raise ValidationError("Дата окончания не может быть раньше даты начала")
        items = await self._plan.list_in_range(household_id, start, end, only_unbought=True)
        cart: dict[int, dict] = {}

        def put(variant_id: int, variant, grams: Decimal) -> None:
            entry = cart.setdefault(
                variant_id,
                {"name": display_name(variant, variant_id), "category": category_name(variant), "weight": ZERO},
            )
            entry["weight"] += grams

        recipes_cache: dict[int, object] = {}
        for item in items:
            need = remaining_weight(item)
            if need <= 0:
                continue
            if item.variant_id is not None:
                put(item.variant_id, item.variant, need)
                continue
            if item.recipe_id is None:
                continue
            if item.recipe_id not in recipes_cache:
                recipes_cache[item.recipe_id] = await self._recipes.get_full(item.recipe_id)
            recipe = recipes_cache[item.recipe_id]
            if recipe is None or _d(recipe.estimated_cooked_weight) <= 0:
                continue
            # доля кастрюли: 600 г готового из выхода 1200 г → половина закладки
            factor = need / _d(recipe.estimated_cooked_weight)
            for ing in recipe.template_ingredients:
                put(ing.variant_id, ing.variant, _d(ing.weight_g) * factor)

        return [
            ShoppingListItem(
                variant_id=vid,
                product_name=e["name"],
                category_name=e["category"],
                weight_g=quantize(e["weight"]),
            )
            for vid, e in sorted(cart.items(), key=lambda kv: (kv[1]["category"] or "", kv[1]["name"]))
        ]

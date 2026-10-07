"""Доменные константы и чистые (не зависящие от БД) вычисления КБЖУ.

Здесь живут правила бизнеса, которые раньше были «размазаны» по роутерам:
статусы записей дневника, валидация согласованности КБЖУ, расчет нутриентов
рецепта/порции. Слой сервисов будет переиспользовать эти функции.
"""
from __future__ import annotations


from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# --- Состояние блюда в плане (выводится из связей MealItem, см. app/models/plan.py) ---
ITEM_PRODUCT = "product"      # готовый продукт: покупается «как есть»
ITEM_TO_COOK = "to_cook"      # рецепт, кастрюли нет — надо приготовить (→ покупки)
ITEM_IN_FRIDGE = "in_fridge"  # рецепт, порции зарезервированы в кастрюле

# Типы приемов пищи (порядок — как в течение дня; используется для сортировки)
MEAL_ORDER: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")
MEAL_TYPES: frozenset[str] = frozenset(MEAL_ORDER)

# Коэффициенты Атвотера для проверки согласованности КБЖУ
KCAL_PER_PROTEIN = Decimal("4")
KCAL_PER_FAT = Decimal("9")
KCAL_PER_CARBS = Decimal("4")
# Допустимое расхождение между указанными и расчетными ккал (на 100 г).
# Реальные этикетки расходятся с формулой Атвотера на 5–15 % (клетчатка ~2 ккал/г,
# округления, полиолы), поэтому ошибкой считаем только расхождение больше
# абсолютного И относительного порога — это ловит опечатки, а не честные данные.
NUTRIENTS_TOLERANCE_ABS = Decimal("10")
NUTRIENTS_TOLERANCE_REL = Decimal("0.15")

ZERO = Decimal("0.0")


@dataclass(frozen=True)
class Nutrients:
    """КБЖУ на 100 г продукта/блюда."""

    calories: Decimal
    proteins: Decimal
    fats: Decimal
    carbs: Decimal


def nutrients_are_inconsistent(n: Nutrients) -> bool:
    """True, если указанные калории расходятся с расчетными сильнее допуска."""
    calculated = (
        KCAL_PER_PROTEIN * n.proteins
        + KCAL_PER_FAT * n.fats
        + KCAL_PER_CARBS * n.carbs
    )
    diff = abs(n.calories - calculated)
    return diff > NUTRIENTS_TOLERANCE_ABS and diff > NUTRIENTS_TOLERANCE_REL * calculated


def scale_nutrients(per_100g: Nutrients, weight_g: Decimal) -> Nutrients:
    """Пересчет КБЖУ с 100 г на произвольный вес (граммы)."""
    factor = weight_g / Decimal("100.0")
    return Nutrients(
        calories=per_100g.calories * factor,
        proteins=per_100g.proteins * factor,
        fats=per_100g.fats * factor,
        carbs=per_100g.carbs * factor,
    )


def per_100g_from_totals(total: Nutrients, cooked_weight_g: Decimal) -> Nutrients:
    """КБЖУ на 100 г готового блюда из суммарных значений сырого набора (с учетом уварки)."""
    if cooked_weight_g <= ZERO:
        raise ValueError("Вес готового блюда должен быть больше 0 грамм")
    factor = Decimal("100.0") / cooked_weight_g
    return Nutrients(
        calories=total.calories * factor,
        proteins=total.proteins * factor,
        fats=total.fats * factor,
        carbs=total.carbs * factor,
    )


def quantize(value: Decimal, places: str = "0.1") -> Decimal:
    """Округление до одного знака (как Numeric(x, 1) в БД), без banker's rounding."""
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)

"""Unit-тесты чистого домена (app/domain.py) — без БД и HTTP."""

from decimal import Decimal

import pytest

from app.domain import (
    Nutrients,
    nutrients_are_inconsistent,
    per_100g_from_totals,
    quantize,
    scale_nutrients,
)


def test_scale_nutrients_proportional():
    per_100 = Nutrients(
        calories=Decimal("100"), proteins=Decimal("10"), fats=Decimal("5"), carbs=Decimal("20")
    )
    scaled = scale_nutrients(per_100, Decimal("250"))
    assert scaled.calories == Decimal("250")
    assert scaled.proteins == Decimal("25")
    assert scaled.fats == Decimal("12.5")
    assert scaled.carbs == Decimal("50")


def test_quantize_one_decimal_place():
    assert quantize(Decimal("10.44")) == Decimal("10.4")
    assert quantize(Decimal("10.45")) in (Decimal("10.4"), Decimal("10.5"))  # ROUND_* допустим оба


def test_per_100g_from_totals():
    totals = Nutrients(
        calories=Decimal("500"), proteins=Decimal("50"), fats=Decimal("25"), carbs=Decimal("100")
    )
    per_100 = per_100g_from_totals(totals, Decimal("1000"))
    assert per_100.calories == Decimal("50.0")
    assert per_100.proteins == Decimal("5.0")


def test_per_100g_zero_weight_raises():
    totals = Nutrients(Z := Decimal("0"), Z, Z, Z)
    with pytest.raises(ValueError):
        per_100g_from_totals(totals, Decimal("0"))


@pytest.mark.parametrize(
    "cal,p,f,c,expected",
    [
        # Атвотер: 4*10 + 9*5 + 4*7.5 = 115 vs 100 → расхождение 15 > допуск 5
        (Decimal("100"), Decimal("10"), Decimal("5"), Decimal("7.5"), True),
        # согласованные значения: расхождение в пределах допуска
        (Decimal("115"), Decimal("10"), Decimal("5"), Decimal("7.5"), False),
        # явное грубое расхождение
        (Decimal("100"), Decimal("10"), Decimal("5"), Decimal("50"), True),
    ],
)
def test_nutrients_are_inconsistent(cal, p, f, c, expected):
    n = Nutrients(calories=cal, proteins=p, fats=f, carbs=c)
    assert nutrients_are_inconsistent(n) is expected

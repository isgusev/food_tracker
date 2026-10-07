"""Unit-тесты чистого домена (app/domain.py) — без БД и HTTP."""
from __future__ import annotations


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
        # согласованные значения
        (Decimal("115"), Decimal("10"), Decimal("5"), Decimal("7.5"), False),
        # честная этикетка гречки: 310 ккал против 345.8 по формуле (−10 %, клетчатка)
        (Decimal("310"), Decimal("12.6"), Decimal("2.6"), Decimal("68"), False),
        # маленькое абсолютное расхождение у малокалорийного продукта (<10 ккал)
        (Decimal("20"), Decimal("1"), Decimal("0"), Decimal("6"), False),
        # опечатка: 100 вместо 350
        (Decimal("100"), Decimal("12"), Decimal("2"), Decimal("70"), True),
        # явное грубое расхождение
        (Decimal("100"), Decimal("10"), Decimal("5"), Decimal("50"), True),
    ],
)
def test_nutrients_are_inconsistent(cal, p, f, c, expected):
    n = Nutrients(calories=cal, proteins=p, fats=f, carbs=c)
    assert nutrients_are_inconsistent(n) is expected



def test_units_and_packages():
    from app.domain import base_to_grams, grams_to_base, pick_packages

    # штучное: 3 яйца по 55 г
    assert grams_to_base(Decimal("165"), "pcs", Decimal("55")) == Decimal("3")
    assert base_to_grams(Decimal("2"), "pcs", Decimal("55")) == Decimal("110")
    # без веса штуки — остаёмся в граммах
    assert grams_to_base(Decimal("165"), "pcs", None) == Decimal("165")
    # 540 г творога: 2×300 (излишек 60) лучше, чем 3×200 (излишек 60, но больше пачек)
    assert pick_packages(Decimal("540"), [Decimal("200"), Decimal("300")], "g") == (Decimal("300"), 2)
    # 350 г: 1×400 (50) лучше 2×200 (50, больше пачек)? равный излишек → меньше упаковок
    assert pick_packages(Decimal("350"), [Decimal("200"), Decimal("400")], "g") == (Decimal("400"), 1)
    # штучное без упаковок — до целых штук
    assert pick_packages(Decimal("2.3"), [], "pcs") == (Decimal("1"), 3)
    assert pick_packages(Decimal("120"), [], "g") == (None, None)

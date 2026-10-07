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


def test_pot_share_multiplies_by_people():
    from app.domain import pot_share

    assert pot_share(Decimal("150"), 3) == Decimal("450")
    assert pot_share(Decimal("150"), None) == Decimal("150")
    assert pot_share(Decimal("150"), 0) == Decimal("150")

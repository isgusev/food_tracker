"""Расчёт рекомендуемых КБЖУ на день под цель: поддержание, снижение, набор веса.

Основа — российские нормы МР 2.3.1.0253-21 («Нормы физиологических потребностей
в энергии и пищевых веществах…», Роспотребнадзор, 2021):
  * основной обмен — формула Миффлина–Сан Жеора (как в самих МР);
  * суточные траты = основной обмен × КФА (1,4 / 1,6 / 1,9 / 2,2);
  * жиры — 30 % калорийности, белки при поддержании — 12–14 % (по КФА).
Под снижение и набор веса:
  * калории: −15 % / +10 % от поддерживающих; при снижении не ниже 1200 ккал
    (женщины) / 1500 ккал (мужчины) — ориентир NIH для безопасной диеты;
  * белок 1,6 г/кг — середина диапазона ISSN (1,4–2,0 г/кг) и порог Morton 2018
    для сохранения/набора мышц; не больше 35 % калорийности (верхняя граница AMDR),
    чтобы при большом весе не получить нереальные цифры.
Формула — для взрослых (18+); точность ±10 % — это ориентир, а не диагноз.
"""
from __future__ import annotations


from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.exceptions import ValidationError

ACTIVITY_LEVELS = {
    Decimal("1.4"): "очень низкая — сидячая работа, почти без движения",
    Decimal("1.6"): "низкая — лёгкий труд, прогулки, 1–3 тренировки в неделю",
    Decimal("1.9"): "средняя — работа на ногах или 3–5 тренировок в неделю",
    Decimal("2.2"): "высокая — тяжёлый физический труд или спорт почти каждый день",
}
GOALS = ("maintain", "lose", "gain")

_PROTEIN_SHARE = {  # доля белка от калорийности при поддержании (МР, п. 1.7)
    Decimal("1.4"): Decimal("0.14"),
    Decimal("1.6"): Decimal("0.13"),
    Decimal("1.9"): Decimal("0.125"),
    Decimal("2.2"): Decimal("0.12"),
}
FAT_SHARE = Decimal("0.30")
PROTEIN_G_PER_KG = Decimal("1.6")
PROTEIN_MAX_SHARE = Decimal("0.35")
LOSE_FACTOR, GAIN_FACTOR = Decimal("0.85"), Decimal("1.10")
MIN_KCAL = {"f": Decimal("1200"), "m": Decimal("1500")}
MIN_CARBS_G = Decimal("130")  # нижняя граница по рекомендациям IOM — для подсказки


@dataclass
class TargetsCalc:
    calories: Decimal
    proteins: Decimal
    fats: Decimal
    carbs: Decimal
    bmr: Decimal
    maintenance: Decimal
    notes: list[str]


def _r(x: Decimal, step: str = "1") -> Decimal:
    return Decimal(x).quantize(Decimal(step), rounding=ROUND_HALF_UP)


def bmr_mifflin(sex: str, age: int, height_cm: Decimal, weight_kg: Decimal) -> Decimal:
    """Основной обмен, ккал/сут (коэффициенты — как в МР 2.3.1.0253-21)."""
    base = Decimal("9.99") * weight_kg + Decimal("6.25") * height_cm - Decimal("4.92") * age
    return base + (Decimal("5") if sex == "m" else Decimal("-161"))


def calc_targets(
    sex: str, age: int, height_cm: Decimal, weight_kg: Decimal, activity: Decimal, goal: str
) -> TargetsCalc:
    if sex not in ("m", "f"):
        raise ValidationError("Укажите пол")
    if goal not in GOALS:
        raise ValidationError("Цель: поддержание, снижение или набор веса")
    activity = _r(activity, "0.1")
    if activity not in ACTIVITY_LEVELS:
        raise ValidationError("Уровень активности: 1,4 / 1,6 / 1,9 / 2,2")
    if not 18 <= age <= 100:
        raise ValidationError("Расчёт по формуле — для взрослых от 18 лет; для детей цели лучше задать с педиатром")
    if not (Decimal(120) <= height_cm <= Decimal(230)) or not (Decimal(30) <= weight_kg <= Decimal(300)):
        raise ValidationError("Проверьте рост (120–230 см) и вес (30–300 кг)")

    notes: list[str] = []
    bmr = bmr_mifflin(sex, age, height_cm, weight_kg)
    maintenance = bmr * activity

    if goal == "maintain":
        kcal = maintenance
        share = Decimal("0.14") if age >= 65 else _PROTEIN_SHARE[activity]
        protein = kcal * share / 4
    else:
        if goal == "lose":
            kcal = maintenance * LOSE_FACTOR
            if kcal < MIN_KCAL[sex]:
                kcal = min(MIN_KCAL[sex], maintenance)
                notes.append(f"Калории подняты до безопасного минимума {MIN_KCAL[sex]} ккал — худеть медленнее, но без вреда.")
        else:
            kcal = maintenance * GAIN_FACTOR
        protein = weight_kg * PROTEIN_G_PER_KG
        cap = kcal * PROTEIN_MAX_SHARE / 4
        if protein > cap:
            protein = cap
            notes.append("Белок ограничен 35 % калорийности (при большом весе 1,6 г/кг — слишком много).")

    kcal = _r(kcal / 10) * 10  # до 10 ккал — точнее формула всё равно не знает
    protein = _r(protein)
    fats = _r(kcal * FAT_SHARE / 9)
    carbs = _r(max(Decimal(0), (kcal - protein * 4 - fats * 9) / 4))
    if carbs < MIN_CARBS_G:
        notes.append("Углеводов меньше 130 г — обычно это минимум для мозга; стоит обсудить с врачом.")
    if age >= 65 and activity > Decimal("1.6"):
        notes.append("Для 65+ нормы ориентируются на КФА 1,7 — проверьте уровень активности.")
    return TargetsCalc(kcal, protein, fats, carbs, _r(bmr), _r(maintenance), notes)

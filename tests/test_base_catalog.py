"""Базовый справочник (миграция 0018): данные согласованы — калории сходятся с БЖУ
по правилу приложения, названия не повторяются, единицы допустимые."""
from __future__ import annotations


import importlib.util
from decimal import Decimal
from pathlib import Path

from app.domain import Nutrients, nutrients_are_inconsistent

def _load(filename: str):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load("0018_base_catalog.py")
more = _load("0019_base_catalog_more.py")
ALL = migration.CATALOG + more.CATALOG


def test_catalog_values_pass_calorie_check():
    bad = []
    for row in ALL:
        _, name, kcal, p, f, c = row[:6]
        if nutrients_are_inconsistent(Nutrients(*(Decimal(str(x)) for x in (kcal, p, f, c)))):
            bad.append(name)
    assert bad == []


def test_catalog_names_unique_and_units_valid():
    names = [row[1].lower() for row in ALL]
    assert len(names) == len(set(names))
    for row in ALL:
        assert all(0 <= x <= 900 for x in row[2:6])
        if len(row) > 6:
            assert row[6] in ("g", "ml", "pcs") and (row[6] != "pcs" or row[7])
    assert len(migration.CATALOG) >= 80 and len(more.CATALOG) >= 15

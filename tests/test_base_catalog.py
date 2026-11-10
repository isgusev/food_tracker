"""Базовый справочник (миграция 0018): данные согласованы — калории сходятся с БЖУ
по правилу приложения, названия не повторяются, единицы допустимые."""
from __future__ import annotations


import importlib.util
from decimal import Decimal
from pathlib import Path

from app.domain import Nutrients, nutrients_are_inconsistent

_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0018_base_catalog.py"
_spec = importlib.util.spec_from_file_location("base_catalog_migration", _path)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def test_catalog_values_pass_calorie_check():
    bad = []
    for row in migration.CATALOG:
        _, name, kcal, p, f, c = row[:6]
        if nutrients_are_inconsistent(Nutrients(*(Decimal(str(x)) for x in (kcal, p, f, c)))):
            bad.append(name)
    assert bad == []


def test_catalog_names_unique_and_units_valid():
    names = [row[1].lower() for row in migration.CATALOG]
    assert len(names) == len(set(names))
    for row in migration.CATALOG:
        assert all(0 <= x <= 900 for x in row[2:6])
        if len(row) > 6:
            assert row[6] in ("g", "ml", "pcs") and (row[6] != "pcs" or row[7])
    assert len(migration.CATALOG) >= 80

"""Импорт рецептов из YAML (docs/RECIPE_IMPORT.md): запрос и отчёт."""
from __future__ import annotations


from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RecipeImportIn(BaseModel):
    """Файл целиком текстом. dry_run — только отчёт, без записи.

    choices — выбор для ингредиентов (ключ из отчёта → variant_id; null — пропустить ингредиент);
    update — номера рецептов (с 1), которые уже есть в семье и которые надо обновить (остальные такие пропускаются)."""

    content: str = Field(min_length=1, max_length=1_000_000)
    dry_run: bool = True
    choices: dict[str, Optional[int]] = {}
    update: list[int] = []


class ImportCandidate(BaseModel):
    variant_id: int
    product_id: int
    name: str
    brand: str = ""
    calories: Decimal
    kbju_missing: bool = False
    score: float = 1.0


class ImportIngredient(BaseModel):
    """Ингредиент файла (одинаковые «продукт + бренд» во всех рецептах — один).

    status: matched — нашёлся по названию; fuzzy — похожий, подставлен, но проверьте; ambiguous — несколько
    похожих, выберите; missing — не нашёлся, выберите или пропустите; chosen — выбран вручную; skipped — пропущен."""

    key: str
    product: str
    brand: str = ""
    status: Literal["matched", "fuzzy", "ambiguous", "missing", "chosen", "skipped"]
    pick: Optional[ImportCandidate] = None
    candidates: list[ImportCandidate] = []
    recipes: list[int] = []      # номера рецептов, где он встречается


class ImportRecipeResult(BaseModel):
    """status до записи: create / update / exists (уже есть — пропустим) / waiting (ждёт выбора продуктов или КБЖУ) /
    error; после записи: created / updated / skipped / waiting / error."""

    number: int
    name: str
    status: Literal["create", "update", "exists", "waiting", "error", "created", "updated", "skipped"]
    category: str = ""
    new_category: bool = False
    servings: Optional[int] = None
    cooked_weight: Optional[Decimal] = None
    calories_per_100g: Optional[Decimal] = None
    ingredients: int = 0
    recipe_id: Optional[int] = None
    errors: list[str] = []
    warnings: list[str] = []


class RecipeImportReport(BaseModel):
    dry_run: bool
    recipes: list[ImportRecipeResult]
    ingredients: list[ImportIngredient]
    created: int = 0
    updated: int = 0

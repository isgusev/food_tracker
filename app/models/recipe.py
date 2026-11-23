"""ORM-модели рецептов: категории, шаблоны, ингредиенты, логи готовки («холодильник»)."""
from __future__ import annotations


from sqlalchemy import (
    JSON,
    CheckConstraint,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class RecipeCategory(Base):
    __tablename__ = "recipe_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    search_name = Column(String(100), unique=True, nullable=False)

    recipes = relationship("Recipe", back_populates="recipe_category")


class Recipe(Base):
    """ШАБЛОН РЕЦЕПТА."""

    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    # Рецепты общие для семьи; user_id — автор
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(   # автор; удалили пользователя — рецепты и кастрюли семьи остаются
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipe_category_id = Column(
        Integer, ForeignKey("recipe_categories.id", ondelete="RESTRICT"), nullable=False
    )
    name = Column(String(255), nullable=False)
    cooking_time_minutes = Column(Integer, nullable=True)
    instructions = Column(Text, nullable=True)
    created_by_user = Column(String(100), nullable=False, default="system")
    default_servings = Column(Integer, default=1, nullable=False)
    # Можно готовить половиной: в покупки — до половины закладки, иначе — целая закладка
    allow_half = Column(Boolean, default=False, nullable=False, server_default="false")
    # --- Автоплан (docs/AUTOPLAN.md, 3.1) ---
    in_rotation = Column(Boolean, default=True, nullable=False, server_default="true")  # предлагать в автоплане
    effort = Column(String(10), default="easy", nullable=False, server_default="easy")  # easy | special
    __table_args__ = (CheckConstraint("effort IN ('easy', 'special')", name="effort"),)
    meal_types = Column(JSON, nullable=True)  # уместные приёмы пищи; NULL — любые
    keeps_days = Column(Integer, default=2, nullable=False, server_default="2")  # сколько дней есть одну закладку
    is_freezable = Column(Boolean, default=False, nullable=False, server_default="false")
    total_raw_weight = Column(Numeric(7, 1), default=0.0, nullable=False)
    estimated_cooked_weight = Column(Numeric(7, 1), nullable=False)
    calories_per_100g = Column(Numeric(5, 1), default=0.0, nullable=False)
    proteins_per_100g = Column(Numeric(4, 1), default=0.0, nullable=False)
    fats_per_100g = Column(Numeric(4, 1), default=0.0, nullable=False)
    carbs_per_100g = Column(Numeric(4, 1), default=0.0, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    recipe_category = relationship("RecipeCategory", back_populates="recipes")
    user = relationship("User")
    template_ingredients = relationship(
        "RecipeTemplateIngredient", back_populates="recipe", cascade="all, delete-orphan"
    )
    cooking_logs = relationship("RecipeCookingLog", back_populates="recipe")

    # --- ЗАДЕЛ НА БУДУЩЕЕ ---
    is_public = Column(Boolean, default=False)  # Флаг для расшаривания в общую базу
    ai_generated = Column(Boolean, default=False)  # Маркер, что рецепт придуман нейросетью


class RecipeTemplateIngredient(Base):
    __tablename__ = "recipe_template_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    weight_g = Column(Numeric(7, 1), nullable=False)
    # «Именно этот вариант»: в покупки — этот продукт с брендом, а не любой того же товара
    exact = Column(Boolean, default=False, nullable=False, server_default="false")

    recipe = relationship("Recipe", back_populates="template_ingredients")
    variant = relationship("ProductVariant")


class RecipeCookingLog(Base):
    """ИНСТАНС ГОТОВКИ (НАШ ХОЛОДИЛЬНИК)."""

    __tablename__ = "recipe_cooking_logs"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Холодильник общий для семьи; user_id — кто готовил
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(   # автор; удалили пользователя — рецепты и кастрюли семьи остаются
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cooked_at = Column(DateTime, server_default=func.now())

    total_raw_weight = Column(Numeric(7, 1), nullable=False)
    total_cooked_weight = Column(Numeric(7, 1), nullable=False)

    # Храним остаток еды в кастрюле
    current_remaining_weight = Column(Numeric(7, 1), nullable=False)
    is_finished = Column(Boolean, default=False, nullable=False)  # Кастрюля пуста?
    # Признак «выбросили/испортилось» (в архиве холодильника помечается как удалённая)
    is_discarded = Column(Boolean, default=False, nullable=False, server_default="false")
    # Заготовка в морозилке: лежит дольше обычного, автоплан ставит её в дни без готовки
    is_frozen = Column(Boolean, default=False, nullable=False, server_default="false")
    keeps_until = Column(Date, nullable=True)  # годно до (у заготовки)

    calories_per_100g = Column(Numeric(5, 1), nullable=False)
    proteins_per_100g = Column(Numeric(4, 1), nullable=False)
    fats_per_100g = Column(Numeric(4, 1), nullable=False)
    carbs_per_100g = Column(Numeric(4, 1), nullable=False)

    actual_ingredients = relationship(
        "RecipeActualIngredient",
        back_populates="cooking_log",
        cascade="all, delete-orphan",
    )
    recipe = relationship("Recipe", back_populates="cooking_logs")

    @property
    def good_until(self):
        """До какого дня есть: заготовка/размороженное — keeps_until, иначе готовка + Recipe.keeps_days.
        Нужна загруженная связь recipe (CookingLogRepository.full_query)."""
        if self.keeps_until is not None:
            return self.keeps_until
        from datetime import timedelta

        from app.core import clock
        days = self.recipe.keeps_days if self.recipe is not None and self.recipe.keeps_days else 2
        return clock.local_date(self.cooked_at) + timedelta(days=days - 1)


class RecipeActualIngredient(Base):
    __tablename__ = "recipe_actual_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    cooking_log_id = Column(
        Integer, ForeignKey("recipe_cooking_logs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    weight_g = Column(Numeric(7, 1), nullable=False)

    cooking_log = relationship("RecipeCookingLog", back_populates="actual_ingredients")
    variant = relationship("ProductVariant")

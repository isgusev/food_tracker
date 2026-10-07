"""ORM-модели рецептов: категории, шаблоны, ингредиенты, логи готовки («холодильник»)."""
from __future__ import annotations


from sqlalchemy import (
    Boolean,
    Column,
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
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipe_category_id = Column(
        Integer, ForeignKey("recipe_categories.id", ondelete="RESTRICT"), nullable=False
    )
    name = Column(String(255), nullable=False)
    cooking_time_minutes = Column(Integer, nullable=True)
    instructions = Column(Text, nullable=True)
    created_by_user = Column(String(100), nullable=False, default="system")
    default_servings = Column(Integer, default=1, nullable=False)
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
        Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    weight_g = Column(Numeric(7, 1), nullable=False)

    recipe = relationship("Recipe", back_populates="template_ingredients")
    variant = relationship("ProductVariant")


class RecipeCookingLog(Base):
    """ИНСТАНС ГОТОВКИ (НАШ ХОЛОДИЛЬНИК)."""

    __tablename__ = "recipe_cooking_logs"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cooked_at = Column(DateTime, server_default=func.now())

    total_raw_weight = Column(Numeric(7, 1), nullable=False)
    total_cooked_weight = Column(Numeric(7, 1), nullable=False)

    # Храним остаток еды в кастрюле
    current_remaining_weight = Column(Numeric(7, 1), nullable=False)
    is_finished = Column(Boolean, default=False, nullable=False)  # Кастрюля пуста?
    # Признак «выбросили/испортилось» (в архиве холодильника помечается как удалённая)
    is_discarded = Column(Boolean, default=False, nullable=False, server_default="false")

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
    diary_entries = relationship("DiaryLog", back_populates="cooking_log")

    # --- ЗАДЕЛ НА БУДУЩЕЕ ---
    household_id = Column(String, index=True, nullable=True)  # ID семьи для общего холодильника


class RecipeActualIngredient(Base):
    __tablename__ = "recipe_actual_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    cooking_log_id = Column(
        Integer, ForeignKey("recipe_cooking_logs.id", ondelete="CASCADE"), nullable=False
    )
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    weight_g = Column(Numeric(7, 1), nullable=False)

    cooking_log = relationship("RecipeCookingLog", back_populates="actual_ingredients")
    variant = relationship("ProductVariant")

"""ORM-модели плана питания семьи: блюдо в плане и порции членов семьи."""
from __future__ import annotations


from sqlalchemy import (
    CheckConstraint,
    Index,
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class MealItem(Base):
    """Блюдо в плане семьи: день + приём пищи + рецепт ИЛИ готовый продукт.

    Состояние выводится из связей:
    - готовый продукт (variant_id) — покупается «как есть»;
    - рецепт без кастрюли — «надо приготовить» (несъеденные порции → покупки);
    - рецепт с кастрюлей (cooking_log_id) — порции зарезервированы в холодильнике.
    """

    __tablename__ = "meal_items"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date_day = Column(Date, nullable=False, index=True)
    meal_type = Column(String(20), nullable=False)

    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True)
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # «Именно этот вариант» готового продукта: в покупки — этот бренд, а не любой того же товара
    exact = Column(Boolean, default=False, nullable=False, server_default="false")
    cooking_log_id = Column(
        Integer, ForeignKey("recipe_cooking_logs.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )

    # Автоплан: manual — поставлено человеком (и всё старое), auto — предложено; ручная правка
    # auto-блюда делает его manual. pinned — «📌 закреплено» (перегенерация не трогает)
    origin = Column(String(10), default="manual", nullable=False, server_default="manual")
    pinned = Column(Boolean, default=False, nullable=False, server_default="false")
    auto_reason = Column(String(200), nullable=True)  # почему предложено: «остаток в холодильнике»

    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())

    recipe = relationship("Recipe")
    variant = relationship("ProductVariant")
    cooking_log = relationship("RecipeCookingLog")
    portions = relationship(
        "MealPortion",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="MealPortion.id",
    )

    __table_args__ = (
        Index("ix_meal_items_household_date", "household_id", "date_day"),   # план семьи за период
        CheckConstraint("meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')", name="meal_type"),
        CheckConstraint("origin IN ('manual', 'auto')", name="origin"),
    )


class MealPortion(Base):
    """Порция одного едока. member_id = NULL — гость (без личного учёта КБЖУ)."""

    __tablename__ = "meal_portions"

    id = Column(Integer, primary_key=True, index=True)
    meal_item_id = Column(
        Integer, ForeignKey("meal_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id = Column(
        Integer, ForeignKey("household_members.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    # План — сколько собирается съесть; после «съедено» — сколько съел по факту
    weight_g = Column(Numeric(6, 1), nullable=False)
    is_eaten = Column(Boolean, default=False, nullable=False)
    # Из какой кастрюли списан съеденный вес (NULL — ели без холодильника).
    # Хранится на порции: блюдо могут отвязать от кастрюли, а списание остаётся.
    eaten_from_pot_id = Column(
        Integer, ForeignKey("recipe_cooking_logs.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    eaten_at = Column(DateTime, nullable=True)

    item = relationship("MealItem", back_populates="portions")
    member = relationship("HouseholdMember")
    eaten_from_pot = relationship("RecipeCookingLog")


class WeekTemplate(Base):
    """Шаблон недели: снимок плана (день недели, приём пищи, блюдо, порции),
    который можно применить к любой неделе."""

    __tablename__ = "week_templates"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False)
    # [{"weekday": 0..6, "meal_type", "recipe_id"|"variant_id", "portions": [{"member_id", "weight_g"}]}]
    items = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class PlanFeedback(Base):
    """Отзыв о предложении автоплана (docs/AUTOPLAN.md, 3.4): что семья сделала с предложенным блюдом.

    accepted — ✓ принято, pinned — 📌 закреплено, replaced — 🔄 заменено, removed — ✕ убрано.
    По рецепту (recipe_id) или по товару готового продукта (item_key). Учитывается в оценке блюд
    с затуханием (app/services/autoplan.py, feedback_scores)."""

    __tablename__ = "plan_feedback"

    id = Column(Integer, primary_key=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True, index=True)
    item_key = Column(String(255), nullable=True)
    meal_type = Column(String(20), nullable=True)
    action = Column(String(10), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_plan_feedback_household_created", "household_id", "created_at"),
        CheckConstraint("action IN ('accepted', 'pinned', 'replaced', 'removed')", name="action"),
    )

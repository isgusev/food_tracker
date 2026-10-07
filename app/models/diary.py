"""ORM-модель дневника питания (планы/факты приемов пищи)."""
from __future__ import annotations


from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.domain import STATUS_TEMPLATE_PLAN


class DiaryLog(Base):
    """ДНЕВНИК ПИТАНИЯ: объединяет планы, уточненные планы и факты приемов пищи."""

    __tablename__ = "diary_logs"

    id = Column(Integer, primary_key=True, index=True)
    # FK на пользователей: изоляция данных проверяется на уровне БД,
    # чужой/несуществующий user_id больше нельзя записать даже теоретически
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # На какую дату запись (например, "2026-06-04")
    date_day = Column(String(10), nullable=False, index=True)

    # Прием пищи: "breakfast", "lunch", "dinner", "snack"
    meal_type = Column(String(20), nullable=False)

    # ТРИ СТАТУСА: "template_plan", "cooked_plan", "fact" (см. app/domain.py)
    status = Column(String(20), default=STATUS_TEMPLATE_PLAN, nullable=False)

    # Связи: блюдо (шаблон рецепта / конкретная готовка) ИЛИ готовый продукт
    recipe_id = Column(
        Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    # Готовый продукт из магазина (йогурт, хлеб…): КБЖУ берутся из версии продукта,
    # в список покупок он попадает «как есть», без разложения на ингредиенты
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=True
    )
    cooking_log_id = Column(
        Integer, ForeignKey("recipe_cooking_logs.id", ondelete="SET NULL"), nullable=True
    )

    # Сколько грамм пользователь планирует съесть или уже съел по факту
    weight_g = Column(Numeric(5, 1), nullable=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    recipe = relationship("Recipe")
    variant = relationship("ProductVariant")
    user = relationship("User")

    # НОВАЯ_ЕСЛИ ЧТО УДАЛИМ
    scale_all_proportions = Column(Boolean, default=False, nullable=True)

    # --- ЗАДЕЛ НА БУДУЩЕЕ ---
    cooking_log = relationship("RecipeCookingLog", back_populates="diary_entries")
    household_id = Column(String, index=True, nullable=True)  # Чтобы видеть планы друг друга
    servings_multiplier = Column(Integer, default=1)  # Множитель порций

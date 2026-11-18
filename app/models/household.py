"""ORM-модели семьи: общая «кухня» (рецепты, холодильник, план) и её члены."""
from __future__ import annotations


from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Household(Base):
    """Семья: всё, что готовится и планируется, принадлежит ей, а не пользователю."""

    __tablename__ = "households"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    # Код приглашения: второй взрослый вводит его и попадает в эту семью
    invite_code = Column(String(16), unique=True, nullable=False)
    # Бюджет на продукты в месяц, ₽ (необязательно)
    monthly_budget = Column(Numeric(10, 2), nullable=True)
    # Допуск, %: кастрюля вышла меньше плана не больше чем на него — порции уменьшаются
    # пропорционально, а не «не хватает»; в покупках — недобор до целой упаковки
    portion_tolerance = Column(Integer, nullable=False, default=15, server_default="15")
    created_at = Column(DateTime, server_default=func.now())

    members = relationship(
        "HouseholdMember", back_populates="household", order_by="HouseholdMember.id"
    )


class HouseholdMember(Base):
    """Член семьи: со своим аккаунтом (user_id) или без него (ребёнок, бабушка).

    Личные цели КБЖУ живут здесь — на сервере, а не в браузере.
    """

    __tablename__ = "household_members"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Пользователь состоит ровно в одной семье
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    name = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    target_calories = Column(Numeric(6, 1), nullable=True)
    target_proteins = Column(Numeric(5, 1), nullable=True)
    target_fats = Column(Numeric(5, 1), nullable=True)
    target_carbs = Column(Numeric(5, 1), nullable=True)

    # Параметры для расчёта целей (app/services/nutrition.py); всё необязательно
    sex = Column(String(1), nullable=True)                 # "m" | "f"
    birth_year = Column(Integer, nullable=True)
    height_cm = Column(Numeric(4, 1), nullable=True)
    weight_kg = Column(Numeric(4, 1), nullable=True)
    activity = Column(Numeric(3, 2), nullable=True)        # КФА: 1.4 / 1.6 / 1.9 / 2.2
    goal = Column(String(8), nullable=True)                # "maintain" | "lose" | "gain"
    __table_args__ = (
        CheckConstraint("sex IN ('m', 'f')", name="sex"),
        CheckConstraint("goal IN ('maintain', 'lose', 'gain')", name="goal"),
    )

    created_at = Column(DateTime, server_default=func.now())

    household = relationship("Household", back_populates="members")
    user = relationship("User")


class PlannerSettings(Base):
    """Настройки автоплана семьи (docs/AUTOPLAN.md, 3.3). Нет строки — значения по умолчанию."""

    __tablename__ = "planner_settings"

    household_id = Column(Integer, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True)
    meal_types = Column(JSON, nullable=True)          # какие приёмы заполнять; NULL — все
    no_cook_days = Column(JSON, nullable=True)        # дни недели без готовки (0 = пн)
    special_days = Column(JSON, nullable=True)        # дни для «эдакого»; пусто — любой
    max_special_per_week = Column(Integer, nullable=False, default=1, server_default="1")
    # Снеки и сладкое (этап 3): категории продуктов семьи и квота ₽ в неделю (NULL — квоты нет)
    snack_categories = Column(JSON, nullable=True)
    snack_quota = Column(Numeric(10, 2), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

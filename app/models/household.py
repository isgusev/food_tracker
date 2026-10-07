"""ORM-модели семьи: общая «кухня» (рецепты, холодильник, план) и её члены."""
from __future__ import annotations


from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String
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

    created_at = Column(DateTime, server_default=func.now())

    household = relationship("Household", back_populates="members")
    user = relationship("User")

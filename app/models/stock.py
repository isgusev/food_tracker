"""ORM-модели запасов семьи и общего списка покупок.

Запасы и покупки сверяются по ТОВАРУ — продукту без учёта бренда
(ключ item_key = Product.search_name); партия помнит конкретный продукт/бренд.

Запасы — это сырьё и упаковки (не готовые блюда — те живут в кастрюлях):
каждая покупка = партия (StockLot), любое изменение остатка = движение
(StockMovement). Движения позволяют точно отменять списания (удалили
кастрюлю, сняли «съел») и потом считать деньги.
"""
from __future__ import annotations


from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class HouseholdProduct(Base):
    """Настройки товара в конкретной семье.

    Товар = продукт без учёта бренда: ключ — название в нижнем регистре
    (Product.search_name), так «гречка» любого бренда — один товар.
    """

    __tablename__ = "household_products"

    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    item_key = Column(String(255), primary_key=True)
    # «Базовый» (соль, масло): остаток не учитывается, в покупки — только с отметкой
    is_staple = Column(Boolean, default=False, nullable=False)
    # «Заканчивается» — для базовых продуктов
    is_low = Column(Boolean, default=False, nullable=False)
    # Списание не нашло остатка — учёт, похоже, разошёлся с реальностью
    needs_check = Column(Boolean, default=False, nullable=False)


class StockLot(Base):
    """Партия: одна покупка (или добавление вручную / по инвентаризации)."""

    __tablename__ = "stock_lots"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Конкретный бренд/версия КБЖУ, если известен
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True
    )
    # Количества — в базовой единице продукта (г / мл / шт)
    quantity = Column(Numeric(9, 1), nullable=False)
    remaining = Column(Numeric(9, 1), nullable=False)
    price = Column(Numeric(10, 2), nullable=True)  # за всю партию
    purchased_on = Column(Date, nullable=False)
    expires_on = Column(Date, nullable=True)
    source = Column(String(16), nullable=False, default="purchase")  # purchase | manual | inventory
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())

    product = relationship("Product")
    variant = relationship("ProductVariant")


class StockMovement(Base):
    """Движение запаса: +покупка, −готовка, −съедено, −списание, ±инвентаризация.

    lot_id = NULL у «недостачи»: списать надо было больше, чем числилось.
    """

    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lot_id = Column(
        Integer, ForeignKey("stock_lots.id", ondelete="CASCADE"), nullable=True, index=True
    )
    delta = Column(Numeric(9, 1), nullable=False)
    reason = Column(String(16), nullable=False)  # purchase | cook | eat | write_off | inventory
    pot_id = Column(
        Integer, ForeignKey("recipe_cooking_logs.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    portion_id = Column(
        Integer, ForeignKey("meal_portions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note = Column(String(200), nullable=True)
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())

    lot = relationship("StockLot")


class ShoppingList(Base):
    """Общий список покупок семьи на период (активный — один на семью)."""

    __tablename__ = "shopping_lists"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(10), nullable=False, default="active")  # active | closed
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    closed_at = Column(DateTime, nullable=True)

    lines = relationship(
        "ShoppingLine",
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingLine.id",
    )

    # Активный список у семьи один: двое одновременно нажали «Сформировать» —
    # второй получит уже созданный, а не дубль
    __table_args__ = (
        Index(
            "uq_shopping_lists_active_household",
            "household_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class ShoppingLine(Base):
    __tablename__ = "shopping_lines"

    id = Column(Integer, primary_key=True, index=True)
    list_id = Column(
        Integer, ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id = Column(
        Integer, ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True
    )
    # Сколько купить (базовая единица) и предложение по упаковкам
    needed = Column(Numeric(9, 1), nullable=True)
    package_amount = Column(Numeric(9, 1), nullable=True)
    package_count = Column(Integer, nullable=True)
    is_extra = Column(Boolean, default=False, nullable=False)    # добавлено вручную
    is_staple = Column(Boolean, default=False, nullable=False)   # «базовый, заканчивается»
    is_checked = Column(Boolean, default=False, nullable=False)
    checked_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checked_at = Column(DateTime, nullable=True)
    # Партия, созданная отметкой «куплено»
    lot_id = Column(
        Integer, ForeignKey("stock_lots.id", ondelete="SET NULL"), nullable=True
    )

    shopping_list = relationship("ShoppingList", back_populates="lines")
    product = relationship("Product")
    variant = relationship("ProductVariant")
    lot = relationship("StockLot")

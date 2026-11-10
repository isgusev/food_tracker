"""ORM-модели кассовых чеков: импорт по QR и выученные соответствия строк чека продуктам.

Чек расшифровывает внешний сервис (code-qr.ru → ФНС), в базу ФНС чеки попадают
с задержкой — поэтому «ждём» (pending) — нормальное состояние, клиент переспрашивает.
"""
from __future__ import annotations


from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.base import Base


class Receipt(Base):
    """Чек: строка QR, статус расшифровки и позиции (как их отдал сервис, нормализованные)."""

    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Строка из QR как есть («t=…&s=…&fn=…&i=…&fp=…&n=1» или ссылка)
    qr_raw = Column(String(500), nullable=False)
    provider_hash = Column(String(64), nullable=True)
    status = Column(String(10), nullable=False, default="pending")  # pending | done | error | applied
    error = Column(String(500), nullable=True)
    store_name = Column(String(255), nullable=True)
    store_inn = Column(String(20), nullable=True)
    purchased_at = Column(DateTime, nullable=True)
    total = Column(Numeric(10, 2), nullable=True)
    # [{"name", "quantity", "price", "sum"}] — числа как в чеке (₽, количество)
    items = Column(JSON, nullable=True)
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())
    applied_at = Column(DateTime, nullable=True)

    # Один и тот же чек семья заносит один раз (повторный скан — тот же чек)
    __table_args__ = (
        UniqueConstraint("household_id", "qr_raw", name="uq_receipts_household_qr"),
    )


class ReceiptAlias(Base):
    """Выученное соответствие: «строка чека этого магазина» → продукт и его количество.

    Запоминается при применении чека; следующий чек того же магазина
    сопоставляется сразу. store_inn = NULL — магазин неизвестен.
    """

    __tablename__ = "receipt_aliases"

    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(
        Integer, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_inn = Column(String(20), nullable=True)
    norm_name = Column(String(255), nullable=False)
    product_id = Column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    # Сколько товара (базовая единица продукта) в ОДНОЙ единице строки чека
    pack_amount = Column(Numeric(9, 1), nullable=True)
    hits = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # NULLS NOT DISTINCT (PostgreSQL 15+): «магазин неизвестен» — тоже один ключ
    __table_args__ = (
        UniqueConstraint(
            "household_id", "store_inn", "norm_name",
            name="uq_receipt_aliases_household_store_name",
            postgresql_nulls_not_distinct=True,
        ),
    )

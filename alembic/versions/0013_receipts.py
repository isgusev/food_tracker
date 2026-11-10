"""кассовые чеки по QR и выученные соответствия строк чека продуктам

Revision ID: 0013_receipts
Revises: 0012_stock_marks
Create Date: 2026-10-16

Таблицы повторяют app/models/receipt.py (DDL сверен с моделями, dialect=postgresql).
Уникальность псевдонима — NULLS NOT DISTINCT (PostgreSQL 15+): строка чека
неизвестного магазина (store_inn = NULL) тоже запоминается ровно один раз.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_receipts"
down_revision = "0012_stock_marks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("qr_raw", sa.String(500), nullable=False),
        sa.Column("provider_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("store_name", sa.String(255), nullable=True),
        sa.Column("store_inn", sa.String(20), nullable=True),
        sa.Column("purchased_at", sa.DateTime(), nullable=True),
        sa.Column("total", sa.Numeric(10, 2), nullable=True),
        sa.Column("items", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"],
            name="fk_receipts_household_id_households", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_receipts_created_by_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_receipts"),
        sa.UniqueConstraint("household_id", "qr_raw", name="uq_receipts_household_qr"),
    )
    op.create_index("ix_receipts_id", "receipts", ["id"])
    op.create_index("ix_receipts_household_id", "receipts", ["household_id"])

    op.create_table(
        "receipt_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("store_inn", sa.String(20), nullable=True),
        sa.Column("norm_name", sa.String(255), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("pack_amount", sa.Numeric(9, 1), nullable=True),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"],
            name="fk_receipt_aliases_household_id_households", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_receipt_aliases_product_id_products", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_receipt_aliases"),
        sa.UniqueConstraint(
            "household_id", "store_inn", "norm_name",
            name="uq_receipt_aliases_household_store_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_receipt_aliases_id", "receipt_aliases", ["id"])
    op.create_index("ix_receipt_aliases_household_id", "receipt_aliases", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_receipt_aliases_household_id", table_name="receipt_aliases")
    op.drop_index("ix_receipt_aliases_id", table_name="receipt_aliases")
    op.drop_table("receipt_aliases")
    op.drop_index("ix_receipts_household_id", table_name="receipts")
    op.drop_index("ix_receipts_id", table_name="receipts")
    op.drop_table("receipts")

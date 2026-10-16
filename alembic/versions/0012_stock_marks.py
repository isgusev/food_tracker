"""пачки с кодами «Честного знака» (срок годности по каждой пачке)

Revision ID: 0012_stock_marks
Revises: 0011_member_body_profile
Create Date: 2026-10-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_stock_marks"
down_revision = "0011_member_body_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_marks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("gtin", sa.String(14), nullable=False),
        sa.Column("serial", sa.String(64), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lot_id"], ["stock_lots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "gtin", "serial", name="_stock_mark_uc"),
    )
    op.create_index(op.f("ix_stock_marks_id"), "stock_marks", ["id"], unique=False)
    op.create_index(op.f("ix_stock_marks_household_id"), "stock_marks", ["household_id"], unique=False)
    op.create_index(op.f("ix_stock_marks_lot_id"), "stock_marks", ["lot_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_marks_lot_id"), table_name="stock_marks")
    op.drop_index(op.f("ix_stock_marks_household_id"), table_name="stock_marks")
    op.drop_index(op.f("ix_stock_marks_id"), table_name="stock_marks")
    op.drop_table("stock_marks")

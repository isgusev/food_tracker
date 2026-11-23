"""семья: допуск кастрюли и упаковок, %

Revision ID: 0021_portion_tolerance
Revises: 0020_base_catalog_extra
Create Date: 2026-11-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0021_portion_tolerance"
down_revision = "0020_base_catalog_extra"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column("portion_tolerance", sa.Integer(), nullable=False, server_default="15"),
    )


def downgrade() -> None:
    op.drop_column("households", "portion_tolerance")

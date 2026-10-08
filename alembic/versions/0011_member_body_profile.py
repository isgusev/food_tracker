"""параметры члена семьи для расчёта целей КБЖУ

Revision ID: 0011_member_body_profile
Revises: 0010_registration_invites
Create Date: 2026-10-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_member_body_profile"
down_revision = "0010_registration_invites"
branch_labels = None
depends_on = None

COLUMNS = [
    ("sex", sa.String(1)),
    ("birth_year", sa.Integer()),
    ("height_cm", sa.Numeric(4, 1)),
    ("weight_kg", sa.Numeric(4, 1)),
    ("activity", sa.Numeric(3, 2)),
    ("goal", sa.String(8)),
]


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("household_members", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("household_members", name)

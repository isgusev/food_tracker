"""регистрация по одноразовым приглашениям

Revision ID: 0010_registration_invites
Revises: 0009_barcode_templates
Create Date: 2026-10-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_registration_invites"
down_revision = "0009_barcode_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("household_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_by_user_id", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"],
                                name="fk_registration_invites_household_id_households", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"],
                                name="fk_registration_invites_created_by_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"],
                                name="fk_registration_invites_used_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_registration_invites"),
        sa.UniqueConstraint("code", name="uq_registration_invites_code"),
    )
    op.create_index("ix_registration_invites_id", "registration_invites", ["id"])


def downgrade() -> None:
    op.drop_table("registration_invites")

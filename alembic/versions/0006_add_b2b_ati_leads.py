"""Add B2B ATI leads table

Revision ID: 7c3b5d8e2f41
Revises: 4b3d2a3f8c10
Create Date: 2025-11-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c3b5d8e2f41"
down_revision: Union[str, Sequence[str], None] = "4b3d2a3f8c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "b2b_ati_leads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("details_received", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'new'")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'b2b_profile_phone'")),
    )
    op.create_index("ix_b2b_ati_leads_uid_created", "b2b_ati_leads", ["uid", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_b2b_ati_leads_uid_created", table_name="b2b_ati_leads")
    op.drop_table("b2b_ati_leads")

"""Add B2B ATI leads table

Revision ID: 7c3b5d8e2f41
Revises: 4b3d2a3f8c10
Create Date: 2025-11-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7c3b5d8e2f41"
down_revision: Union[str, Sequence[str], None] = "4b3d2a3f8c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "b2b_ati_leads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'new'")),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("b2b_ati_leads")

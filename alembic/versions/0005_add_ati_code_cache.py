"""Add ATI code cache table

Revision ID: 4b3d2a3f8c10
Revises: 2c4de94cf28c
Create Date: 2025-11-17 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4b3d2a3f8c10"
down_revision: Union[str, Sequence[str], None] = "2c4de94cf28c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ati_code_cache",
        sa.Column("ati_id", sa.String(length=10), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("canonical_ati_id", sa.String(length=10), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("ati_code_cache")

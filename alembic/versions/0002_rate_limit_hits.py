"""Add rate limit hits table

Revision ID: 5a2d5d3f4a77
Revises: d42954ad33d6
Create Date: 2025-01-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5a2d5d3f4a77"
down_revision: Union[str, Sequence[str], None] = "d42954ad33d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_rl_uid_scope_ts",
        "rate_limit_hits",
        ["uid", "scope", sa.text("ts DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_rl_uid_scope_ts", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")

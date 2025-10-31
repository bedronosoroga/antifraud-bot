"""Add user notifications table and indexes

Revision ID: 1f8b8b8c6a2d
Revises: 5a2d5d3f4a77
Create Date: 2025-01-17 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1f8b8b8c6a2d"
down_revision: Union[str, Sequence[str], None] = "5a2d5d3f4a77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_un_uid_kind",
        "user_notifications",
        ["uid", "kind"],
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_un_uid_kind_day
            ON user_notifications (uid, kind, ((sent_at AT TIME ZONE 'UTC')::date))
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_subs_expires_at ON subs (expires_at)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_free_grants_expires_at ON free_grants (expires_at)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_free_grants_expires_at"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_subs_expires_at"))
    op.execute(sa.text("DROP INDEX IF EXISTS uq_un_uid_kind_day"))
    op.drop_index("idx_un_uid_kind", table_name="user_notifications")
    op.drop_table("user_notifications")

"""Add referral locks table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0008_add_ref_locks"
down_revision = "0007_add_yk_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_locks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_kop", sa.BigInteger(), nullable=False),
        sa.Column("unlock_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("refunded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ref_locks_uid_refunded", "ref_locks", ["uid", "refunded"])
    op.create_index("ix_ref_locks_payment", "ref_locks", ["payment_id", "provider"])


def downgrade() -> None:
    op.drop_index("ix_ref_locks_payment", table_name="ref_locks")
    op.drop_index("ix_ref_locks_uid_refunded", table_name="ref_locks")
    op.drop_table("ref_locks")

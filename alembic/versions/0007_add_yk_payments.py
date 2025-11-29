"""Add YooKassa payments table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007_add_yk_payments"
down_revision = "7c3b5d8e2f41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "yk_payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_qty", sa.Integer(), nullable=False),
        sa.Column("package_price_rub", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'yookassa'")),
        sa.Column("yk_payment_id", sa.Text(), nullable=True),
        sa.Column("confirmation_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'created'")),
        sa.Column("granted_requests", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_yk_payments_status", "yk_payments", ["status"])
    op.create_index("ix_yk_payments_uid", "yk_payments", ["uid"])
    op.create_index("ix_yk_payments_yk_payment_id", "yk_payments", ["yk_payment_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_yk_payments_yk_payment_id", table_name="yk_payments")
    op.drop_index("ix_yk_payments_uid", table_name="yk_payments")
    op.drop_index("ix_yk_payments_status", table_name="yk_payments")
    op.drop_table("yk_payments")

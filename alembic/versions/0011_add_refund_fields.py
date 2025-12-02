"""Add refund fields to yk_payments"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011_add_refund_fields"
down_revision = "0010_add_admin_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("yk_payments", sa.Column("telegram_charge_id", sa.Text(), nullable=True))
    op.add_column("yk_payments", sa.Column("hold_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("yk_payments", sa.Column("refunded", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("yk_payments", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("yk_payments", sa.Column("refund_source", sa.Text(), nullable=True))
    op.create_index("ix_yk_payments_charge_id", "yk_payments", ["telegram_charge_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_yk_payments_charge_id", table_name="yk_payments")
    op.drop_column("yk_payments", "refund_source")
    op.drop_column("yk_payments", "refunded_at")
    op.drop_column("yk_payments", "refunded")
    op.drop_column("yk_payments", "hold_until")
    op.drop_column("yk_payments", "telegram_charge_id")

"""init schema

Revision ID: d42954ad33d6
Revises:
Create Date: 2025-10-29 15:12:06.214265

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "d42954ad33d6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    plan_enum = sa.Enum("none", "p20", "p50", "unlim", name="plan_enum")
    risk_enum = sa.Enum("none", "elevated", "critical", "scarce", "unknown", name="risk_enum")
    report_enum = sa.Enum("A", "B", "C", "D", "E", name="report_enum")
    payment_status_enum = sa.Enum("waiting", "confirmed", "rejected", name="payment_status_enum")

    for enum in (plan_enum, risk_enum, report_enum, payment_status_enum):
        enum.create(bind=bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("company_ati", sa.String(length=7), nullable=True),
        sa.CheckConstraint("company_ati ~ '^[0-9]{1,7}$'", name="ck_users_company_ati_format"),
    )

    op.create_table(
        "subs",
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan", sa.Enum("none", "p20", "p50", "unlim", name="plan_enum", create_type=False), nullable=False, server_default=sa.text("'none'::plan_enum")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checks_left", sa.Integer(), nullable=True),
        sa.Column("day_cap_left", sa.Integer(), nullable=True),
        sa.Column("last_day_reset", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ati", sa.String(length=7), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lin", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("exp", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("risk", sa.Enum("none", "elevated", "critical", "scarce", "unknown", name="risk_enum", create_type=False), nullable=False),
        sa.Column("report_type", sa.Enum("A", "B", "C", "D", "E", name="report_enum", create_type=False), nullable=False),
        sa.CheckConstraint("ati ~ '^[0-9]{1,7}$'", name="ck_history_ati_format"),
    )
    op.execute("CREATE INDEX ix_history_uid_ts_desc ON history (uid, ts DESC)")
    op.create_index("ix_history_ati", "history", ["ati"])

    op.create_table(
        "user_flags",
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("unlimited_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "referrals",
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("referred_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("paid_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tier", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("percent", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("balance_kop", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "ref_payouts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_kop", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.Enum("waiting", "confirmed", "rejected", name="payment_status_enum", create_type=False), nullable=False),
    )

    op.create_table(
        "pending_payments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.Enum("none", "p20", "p50", "unlim", name="plan_enum", create_type=False), nullable=False),
        sa.Column("amount_kop", sa.Integer(), nullable=False),
        sa.Column("provider_invoice_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("waiting", "confirmed", "rejected", name="payment_status_enum", create_type=False), nullable=False, server_default=sa.text("'waiting'::payment_status_enum")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metadata", pg.JSONB(), nullable=True),
    )
    op.create_index("ix_pending_payments_uid_status", "pending_payments", ["uid", "status"])

    op.create_table(
        "free_grants",
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("used", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("free_grants")
    op.drop_index("ix_pending_payments_uid_status", table_name="pending_payments")
    op.drop_table("pending_payments")
    op.drop_table("ref_payouts")
    op.drop_table("referrals")
    op.drop_table("user_flags")
    op.drop_index("ix_history_ati", table_name="history")
    op.execute("DROP INDEX IF EXISTS ix_history_uid_ts_desc")
    op.drop_table("history")
    op.drop_table("subs")
    op.drop_table("users")

    for enum in (
        sa.Enum(name="payment_status_enum"),
        sa.Enum(name="report_enum"),
        sa.Enum(name="risk_enum"),
        sa.Enum(name="plan_enum"),
    ):
        try:
            enum.drop(bind=bind, checkfirst=True)
        except Exception:
            pass

"""Add quota tables and extend referrals

Revision ID: 2c4de94cf28c
Revises: 1f8b8b8c6a2d
Create Date: 2025-02-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2c4de94cf28c"
down_revision: Union[str, Sequence[str], None] = "1f8b8b8c6a2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for plan_code in ("pkg5", "pkg15", "pkg35", "pkg75", "pkg150", "pkg500"):
        op.execute(sa.text(f"ALTER TYPE plan_enum ADD VALUE IF NOT EXISTS '{plan_code}'"))

    op.create_table(
        "quota_balances",
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_daily_grant", sa.Date(), nullable=True),
    )

    op.create_table(
        "quota_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("uid", "event_key", name="uq_quota_events_uid_key"),
    )
    op.create_index("idx_quota_events_uid", "quota_events", ["uid"])

    op.add_column(
        "referrals",
        sa.Column("total_earned_kop", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "referrals",
        sa.Column("paid_refs_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "referrals",
        sa.Column("first_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "referrals",
        sa.Column(
            "inviter_bonus_granted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "referrals",
        sa.Column("custom_tag", sa.Text(), nullable=True),
    )
    op.add_column(
        "referrals",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_referrals_custom_tag", "referrals", ["custom_tag"])
    op.create_index("idx_referrals_referred_by", "referrals", ["referred_by"])
    op.add_column(
        "ref_payouts",
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_index("idx_referrals_referred_by", table_name="referrals")
    op.drop_constraint("uq_referrals_custom_tag", "referrals", type_="unique")
    op.drop_column("referrals", "created_at")
    op.drop_column("referrals", "custom_tag")
    op.drop_column("referrals", "inviter_bonus_granted")
    op.drop_column("referrals", "first_paid_at")
    op.drop_column("referrals", "paid_refs_count")
    op.drop_column("referrals", "total_earned_kop")
    op.drop_index("idx_quota_events_uid", table_name="quota_events")
    op.drop_table("quota_events")
    op.drop_table("quota_balances")
    op.drop_column("ref_payouts", "details")

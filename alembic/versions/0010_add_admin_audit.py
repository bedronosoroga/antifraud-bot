"""Add admin_audit table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0010_add_admin_audit"
down_revision = "0009_add_user_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("admin_uid", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_admin_audit_ts", "admin_audit", ["ts"])
    op.create_index("ix_admin_audit_admin", "admin_audit", ["admin_uid"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_admin", table_name="admin_audit")
    op.drop_index("ix_admin_audit_ts", table_name="admin_audit")
    op.drop_table("admin_audit")

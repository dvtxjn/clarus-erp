"""users: read_only — a view-only login that can't change anything (the QA bot, client 2026-10-07)

Revision ID: 0054
Revises: 0053
"""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_column("read_only")

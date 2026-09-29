"""users: password reset requests + last login (passwords are set by the admin only)

Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("password_reset_requested_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_column("last_login_at")
        b.drop_column("password_reset_requested_at")

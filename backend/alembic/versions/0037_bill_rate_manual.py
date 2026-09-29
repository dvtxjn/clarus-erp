"""proformas: was the HSS bill rate typed by hand? (otherwise it follows the rules)

Existing rates are treated as typed by hand, so nothing already on a proforma moves.

Revision ID: 0037
Revises: 0036
"""
from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proformas") as b:
        b.add_column(sa.Column("bill_rate_manual", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE proformas SET bill_rate_manual = TRUE WHERE bill_rate IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("proformas") as b:
        b.drop_column("bill_rate_manual")

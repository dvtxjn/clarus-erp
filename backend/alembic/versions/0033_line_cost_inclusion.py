"""Shipping line in cost inclusion: per-shipment switch + per-organisation default

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shipments") as b:
        b.add_column(sa.Column("line_cost_inclusion", sa.String(), nullable=True))
    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("line_in_cost_inclusion", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("organizations") as b:
        b.drop_column("line_in_cost_inclusion")
    with op.batch_alter_table("shipments") as b:
        b.drop_column("line_cost_inclusion")

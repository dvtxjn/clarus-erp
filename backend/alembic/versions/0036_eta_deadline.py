"""shipments: ETA can be marked a deadline (the small "d" on the ETA in the tracker)

Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shipments") as b:
        b.add_column(sa.Column("eta_is_deadline", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("shipments") as b:
        b.drop_column("eta_is_deadline")

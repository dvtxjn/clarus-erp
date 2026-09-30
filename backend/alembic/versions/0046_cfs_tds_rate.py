"""shipments.cfs_tds_rate: TDS % on the CFS payment when not the usual 2% (client, 2026-09-30)

Empty = 2%. Other rates (1%, 10%, custom) only once the admin turns on "tds_rate_editable" in Settings.

Revision ID: 0046
Revises: 0045
"""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("cfs_tds_rate", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("shipments", "cfs_tds_rate")

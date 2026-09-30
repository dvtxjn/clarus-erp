"""per-container free days at the FPOD (default 14) + a typed tracking status (e.g. "On rail")

Revision ID: 0042
Revises: 0041
"""
from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipment_containers", sa.Column("free_days", sa.Integer(), nullable=True))
    op.add_column("shipment_containers", sa.Column("tracking_status", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("shipment_containers", "tracking_status")
    op.drop_column("shipment_containers", "free_days")

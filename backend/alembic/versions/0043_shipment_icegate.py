"""ICEGATE read-out per shipment: sea IGM extras + ICD BL details (JSON)

Revision ID: 0043
Revises: 0042
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipments", sa.Column("icegate", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("shipments", "icegate")

"""shipment_containers.do_valid_until: the container's validity read from the DO (client, 2026-10-05)

The DO's validity / empty-return date is the container's actual last free date until the DO is revalidated.

Revision ID: 0049
Revises: 0048
"""
from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipment_containers", sa.Column("do_valid_until", sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column("shipment_containers", "do_valid_until")

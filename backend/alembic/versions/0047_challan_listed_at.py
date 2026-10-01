"""duty_challans.listed_at: when ICEGATE generated the challan list (client, 2026-10-01)

The .xlsx carries its own creation time, so yesterday's file uploaded today no longer counts as today's.
Existing rows: listed_at = uploaded_at.

Revision ID: 0047
Revises: 0046
"""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("duty_challans", sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_duty_challans_listed_at", "duty_challans", ["listed_at"])
    op.execute("UPDATE duty_challans SET listed_at = uploaded_at")


def downgrade() -> None:
    op.drop_index("ix_duty_challans_listed_at", "duty_challans")
    op.drop_column("duty_challans", "listed_at")

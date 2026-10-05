"""HMM MBLs stored with their HDMU prefix: BHMA… -> HDMUBHMA… (client, 2026-10-05)

New and imported MBLs are standardised by Shipment's validator; this brings the existing rows in line.

Revision ID: 0050
Revises: 0049
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE shipments SET mbl = 'HDMU' || UPPER(TRIM(mbl)) WHERE UPPER(TRIM(mbl)) LIKE 'BHMA%'")


def downgrade() -> None:
    pass  # both spellings are the same BL; nothing to undo

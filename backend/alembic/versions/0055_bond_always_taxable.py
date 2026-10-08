"""charges: bond is always taxable (client, 2026-10-09) — the old "Bond Charges (Reimbursement)"
(BONDC) moves to Billed by Clarus and is switched off; Bond Charges (SBOND) is the one to use.
Existing proforma lines are left as they are.

Revision ID: 0055
Revises: 0054
"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE charge_master_entries SET category='SERVICE', is_active=:f WHERE code='BONDC'"), {"f": False})


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE charge_master_entries SET category='REIMBURSEMENT', is_active=:t WHERE code='BONDC'"), {"t": True})

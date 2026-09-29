"""standard rates: Bond (SBOND) and Documentation (DC) 1500 each

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

RATES = {"SBOND": 1500, "DC": 1500}  # client, 2026-09-28


def upgrade() -> None:
    conn = op.get_bind()
    for code, rate in RATES.items():
        conn.execute(sa.text("UPDATE charge_master_entries SET default_rate=:r WHERE code=:c AND default_rate IS NULL"),
                     {"r": rate, "c": code})


def downgrade() -> None:
    conn = op.get_bind()
    for code, rate in RATES.items():
        conn.execute(sa.text("UPDATE charge_master_entries SET default_rate=NULL WHERE code=:c AND default_rate=:r"),
                     {"r": rate, "c": code})

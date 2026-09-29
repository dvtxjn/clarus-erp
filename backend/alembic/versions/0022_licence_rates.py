"""licence rates: charges pre-filled on proformas per licence (client rates, 2026-09-28)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-28
"""
import json

from alembic import op
import sqlalchemy as sa

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None

AGENCY = {"code": "AC", "per_container": 7000}
# per container (client, 2026-09-28)
EXAM_BY_PORT = [{"code": "EC", "port": "INNSA1", "per_container": 2000},
                {"code": "EC", "port": "INMUN1", "per_container": 3000},
                {"code": "EC", "port": "INDWN6", "per_container": 3000}]
LICENCES = [
    ("111022154", "MAHRISHI RECYCLERS", True, [AGENCY, *EXAM_BY_PORT,
        {"code": "SBOND", "seller": "HKR", "flat": 2000}, {"code": "DC", "seller": "HKR", "flat": 2000},
        {"code": "SBOND", "seller": "Earthman", "flat": 1000}, {"code": "DC", "seller": "Earthman", "flat": 1000},
        {"code": "SBOND", "seller": "Earthstar", "flat": 1000}, {"code": "DC", "seller": "Earthstar", "flat": 1000}],
     "Other Charges per the HSS rule"),
    ("111035337", "Devine Industries", True, [AGENCY, {"code": "EC", "flat": 3000}], None),
    ("111035316", "EARTHMAN RUBBER INDUSTRIES PRIVATE LIMITED", True, [AGENCY, *EXAM_BY_PORT], None),
    ("111021955", "HOME ZONE RUBBER SOLUTIONS LIMITED", True,
     [AGENCY, {"code": "OTHERCHARGES", "per_container": 20000}, {"code": "EC", "flat": 3000}], None),
    ("111021207", "Devine Industries", False, [], "Licence done and dusted"),
]


def upgrade() -> None:
    op.create_table(
        'licences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('number', sa.String(), nullable=False),
        sa.Column('importer_name', sa.String(), nullable=True),
        sa.Column('rates', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_licences_number', 'licences', ['number'], unique=True)
    conn = op.get_bind()
    for number, importer, active, rates, notes in LICENCES:
        conn.execute(sa.text("INSERT INTO licences (number, importer_name, rates, is_active, notes) "
                             "VALUES (:n, :i, :r, :a, :o)"),
                     {"n": number, "i": importer, "r": json.dumps(rates), "a": active, "o": notes})


def downgrade() -> None:
    op.drop_index('ix_licences_number', table_name='licences')
    op.drop_table('licences')

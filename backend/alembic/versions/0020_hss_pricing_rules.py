"""HSS pricing rules (per BE importer, per seller / buyer copy) + the Mahrishi rule; Royalty section

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-28
"""
import json

from alembic import op
import sqlalchemy as sa

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

MAHRISHI = {
    "seller": [{"code": "ROY", "per_kg": 1}, {"code": "OTHERCHARGES", "per_container": 20000}],
    "buyer": [{"code": "ROY", "per_kg": 0.75}, {"code": "OTHERCHARGES", "per_container": 20000, "per_kg": 0.25}],
}


def upgrade() -> None:
    op.create_table(
        'pricing_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('importer_name', sa.String(), nullable=False),
        sa.Column('bill_to_role', sa.String(), nullable=False),
        sa.Column('lines', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    conn = op.get_bind()
    for role, lines in MAHRISHI.items():
        conn.execute(sa.text("INSERT INTO pricing_rules (name, importer_name, bill_to_role, lines, is_active) "
                             "VALUES (:n, 'MAHRISHI RECYCLERS', :r, :l, 1)"),
                     {"n": f"Mahrishi HSS — {role} copy", "r": role, "l": json.dumps(lines)})


    # Royalty gets its own invoice section (existing Royalty lines move with it)
    conn.execute(sa.text("UPDATE charge_master_entries SET category='ROYALTY' WHERE code='ROY'"))
    conn.execute(sa.text("UPDATE proforma_line_items SET category='ROYALTY' WHERE charge_master_id IN "
                         "(SELECT id FROM charge_master_entries WHERE code='ROY')"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE proforma_line_items SET category='REIMBURSEMENT' WHERE category='ROYALTY'"))
    conn.execute(sa.text("UPDATE charge_master_entries SET category='REIMBURSEMENT' WHERE category='ROYALTY'"))
    op.drop_table('pricing_rules')

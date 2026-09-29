"""HSS shipments and proforma name / bill-to

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_hss', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('hss_seller', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('hss_buyer', sa.String(), nullable=True))
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('bill_to', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('bill_to_role', sa.String(), nullable=True))

    # Client rule: a consignee with '-' in it ("SELLER - BUYER") is an HSS shipment
    conn = op.get_bind()
    for sid, consignee in conn.execute(sa.text("SELECT id, consignee FROM shipments WHERE consignee LIKE '%-%'")).fetchall():
        seller, buyer = (p.strip() for p in consignee.split("-", 1))
        if seller and buyer:
            conn.execute(sa.text("UPDATE shipments SET is_hss=1, hss_seller=:s, hss_buyer=:b WHERE id=:i"),
                         {"s": seller, "b": buyer, "i": sid})
    # existing proformas are addressed to the consignee
    conn.execute(sa.text("UPDATE proformas SET bill_to = (SELECT consignee FROM shipments WHERE shipments.id = proformas.shipment_id)"))


def downgrade() -> None:
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.drop_column('bill_to_role')
        batch_op.drop_column('bill_to')
        batch_op.drop_column('name')
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.drop_column('hss_buyer')
        batch_op.drop_column('hss_seller')
        batch_op.drop_column('is_hss')

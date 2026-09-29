"""shipping line proforma / receipt, CFS receipt document types; shipping line paid by us; CFS billed as

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

NEW_OPTIONAL = ('SHIPPING_LINE_PROFORMA', 'SHIPPING_LINE_RECEIPT', 'CFS_RECEIPT')


def upgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_paid_by_us', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('cfs_billed_as', sa.String(), server_default='reimbursement', nullable=False))
    conn = op.get_bind()
    for (hs_id,) in conn.execute(sa.text("SELECT id FROM hs_codes")).fetchall():
        for t in NEW_OPTIONAL:
            if not conn.execute(sa.text("SELECT 1 FROM required_documents WHERE hs_code_id=:h AND document_type=:t"),
                                {"h": hs_id, "t": t}).first():
                conn.execute(sa.text("INSERT INTO required_documents (hs_code_id, document_type, optional) "
                                     "VALUES (:h, :t, 1)"), {"h": hs_id, "t": t})


def downgrade() -> None:
    conn = op.get_bind()
    for t in NEW_OPTIONAL:
        conn.execute(sa.text("DELETE FROM required_documents WHERE document_type=:t"), {"t": t})
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.drop_column('cfs_billed_as')
        batch_op.drop_column('line_paid_by_us')

"""shipping line destination charges invoice

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_amount_before_tax', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('line_gst_amount', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('line_amount_total', sa.Numeric(precision=14, scale=2), nullable=True))

    # Every HS code's checklist gets the shipping line destination charges invoice
    conn = op.get_bind()
    for (hs_id,) in conn.execute(sa.text("SELECT id FROM hs_codes")).fetchall():
        exists = conn.execute(sa.text(
            "SELECT 1 FROM required_documents WHERE hs_code_id=:h AND document_type='SHIPPING_LINE_INVOICE'"),
            {"h": hs_id}).first()
        if not exists:
            conn.execute(sa.text("INSERT INTO required_documents (hs_code_id, document_type, optional) "
                                 "VALUES (:h, 'SHIPPING_LINE_INVOICE', 0)"), {"h": hs_id})


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM required_documents WHERE document_type='SHIPPING_LINE_INVOICE'"))
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.drop_column('line_amount_total')
        batch_op.drop_column('line_gst_amount')
        batch_op.drop_column('line_amount_before_tax')

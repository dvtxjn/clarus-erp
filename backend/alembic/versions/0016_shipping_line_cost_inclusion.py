"""shipping line invoices: cost inclusion per invoice (INR charges only, or a figure typed by hand)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipment_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cost_before_tax', sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column('cost_gst', sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column('cost_excluded', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('cost_manual', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('shipment_documents', schema=None) as batch_op:
        batch_op.drop_column('cost_manual')
        batch_op.drop_column('cost_excluded')
        batch_op.drop_column('cost_gst')
        batch_op.drop_column('cost_before_tax')

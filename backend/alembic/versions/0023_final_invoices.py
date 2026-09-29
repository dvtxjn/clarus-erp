"""final invoices (tax / reimbursement) + invoice number series per financial year

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'final_invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shipment_id', sa.Integer(), sa.ForeignKey('shipments.id'), nullable=False),
        sa.Column('proforma_id', sa.Integer(), sa.ForeignKey('proformas.id'), nullable=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=True),
        sa.Column('fy', sa.String(), nullable=True),
        sa.Column('number', sa.String(), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('customer', sa.JSON(), nullable=False),
        sa.Column('header', sa.JSON(), nullable=False),
        sa.Column('lines', sa.JSON(), nullable=False),
        sa.Column('advance_received', sa.Numeric(14, 2), server_default='0', nullable=False),
        sa.Column('remarks', sa.String(), nullable=True),
        sa.Column('irn', sa.String(), nullable=True),
        sa.Column('ack_no', sa.String(), nullable=True),
        sa.Column('ack_date', sa.String(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number'),
    )
    op.create_index('ix_final_invoices_shipment_id', 'final_invoices', ['shipment_id'])
    op.create_table(
        'invoice_counters',
        sa.Column('fy', sa.String(), nullable=False),
        sa.Column('next_seq', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('fy'),
    )
    # the client's series: CL/200/26-27 was issued on 15-Sep-2026 -> continue from 201 (editable)
    op.get_bind().execute(sa.text("INSERT INTO invoice_counters (fy, next_seq) VALUES ('26-27', 201)"))


def downgrade() -> None:
    op.drop_table('invoice_counters')
    op.drop_index('ix_final_invoices_shipment_id', table_name='final_invoices')
    op.drop_table('final_invoices')

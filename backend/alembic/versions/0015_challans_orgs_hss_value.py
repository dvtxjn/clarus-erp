"""duty challans, organization details, proforma bill rate / bill-to org, royalty + GST difference charges

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

ORG_COLUMNS = ("short_names", "gstin", "pan", "iec", "address", "state", "email", "phone")


def upgrade() -> None:
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.alter_column('ad_code', existing_type=sa.String(length=7), nullable=True)
        for col in ORG_COLUMNS:
            batch_op.add_column(sa.Column(col, sa.String(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'duty_challans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('be_no', sa.String(), nullable=False),
        sa.Column('be_date', sa.String(), nullable=True),
        sa.Column('location_code', sa.String(), nullable=True),
        sa.Column('iec', sa.String(), nullable=True),
        sa.Column('challan_no', sa.String(), nullable=True),
        sa.Column('due_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('source', sa.String(), nullable=False, server_default='upload'),
        sa.Column('filename', sa.String(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_duty_challans_be_no', 'duty_challans', ['be_no'])

    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bill_rate', sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column('bill_to_org_id', sa.Integer(), nullable=True))

    # Royalty (HSS only, per kg, template: 0.75/kg + 18% GST, total rounded up) and the
    # automatic GST Difference line (template row 33)
    conn = op.get_bind()
    rows = [("Royalty", "ROY", "18.00", "PER_KG", "0.75"), ("GST Difference", "GSTD", "0.00", "FLAT", None)]
    for name, code, gst, basis, rate in rows:
        if conn.execute(sa.text("SELECT 1 FROM charge_master_entries WHERE code=:c"), {"c": code}).first():
            continue
        conn.execute(sa.text(
            "INSERT INTO charge_master_entries (name, code, sac_code, gst_rate, calculation_basis, category, "
            "default_rate, is_active) VALUES (:n, :c, '996713', :g, :b, 'REIMBURSEMENT', :r, 1)"),
            {"n": name, "c": code, "g": gst, "b": basis, "r": rate})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM charge_master_entries WHERE code IN ('ROY', 'GSTD') AND id NOT IN "
                         "(SELECT charge_master_id FROM proforma_line_items)"))
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.drop_column('bill_to_org_id')
        batch_op.drop_column('bill_rate')
    op.drop_index('ix_duty_challans_be_no', table_name='duty_challans')
    op.drop_table('duty_challans')
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
        for col in reversed(ORG_COLUMNS):
            batch_op.drop_column(col)
        batch_op.alter_column('ad_code', existing_type=sa.String(length=7), nullable=False)

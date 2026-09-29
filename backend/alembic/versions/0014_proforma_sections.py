"""proforma sections: charge category, line category / actual GST, template rates

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None

REIMBURSEMENT = ("CD", "CDB", "SD", "CFS", "INS", "BONDC", "DELIVERYCHARGE", "TC", "YARD", "LOLO")
COST_INCLUSION = ("DO",)
DEFAULT_RATES = {"AC": 7000, "EC": 18000}  # per container, from the client's template


def upgrade() -> None:
    category = sa.Enum('SERVICE', 'REIMBURSEMENT', 'COST_INCLUSION', name='chargecategory', native_enum=False, length=40)
    with op.batch_alter_table('charge_master_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', category, server_default='SERVICE', nullable=False))
    with op.batch_alter_table('proforma_line_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', category, server_default='SERVICE', nullable=False))
        batch_op.add_column(sa.Column('gst_is_actual', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False))

    conn = op.get_bind()
    codes = lambda c: sa.bindparam(c, expanding=True)  # noqa: E731
    conn.execute(sa.text("UPDATE charge_master_entries SET category='REIMBURSEMENT' WHERE code IN :r")
                 .bindparams(codes("r")), {"r": list(REIMBURSEMENT)})
    conn.execute(sa.text("UPDATE charge_master_entries SET category='COST_INCLUSION' WHERE code IN :c")
                 .bindparams(codes("c")), {"c": list(COST_INCLUSION)})
    for code, rate in DEFAULT_RATES.items():
        conn.execute(sa.text("UPDATE charge_master_entries SET default_rate=:r WHERE code=:c AND default_rate IS NULL"),
                     {"r": rate, "c": code})
    # existing line items take their charge's category
    conn.execute(sa.text(
        "UPDATE proforma_line_items SET category = (SELECT category FROM charge_master_entries c "
        "WHERE c.id = proforma_line_items.charge_master_id)"))


def downgrade() -> None:
    with op.batch_alter_table('proforma_line_items', schema=None) as batch_op:
        batch_op.drop_column('sort_order')
        batch_op.drop_column('gst_is_actual')
        batch_op.drop_column('category')
    with op.batch_alter_table('charge_master_entries', schema=None) as batch_op:
        batch_op.drop_column('category')

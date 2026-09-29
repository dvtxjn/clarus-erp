"""HSS pricing rules: seller defined too (blank = any seller)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('pricing_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seller_name', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('pricing_rules', schema=None) as batch_op:
        batch_op.drop_column('seller_name')

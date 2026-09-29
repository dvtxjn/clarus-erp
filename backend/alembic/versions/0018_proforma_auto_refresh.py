"""proforma auto-refresh: hand-edited lines, remembered removals

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('proforma_line_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_manual', sa.Boolean(), server_default='0', nullable=False))
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('suppressed', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.drop_column('suppressed')
    with op.batch_alter_table('proforma_line_items', schema=None) as batch_op:
        batch_op.drop_column('is_manual')

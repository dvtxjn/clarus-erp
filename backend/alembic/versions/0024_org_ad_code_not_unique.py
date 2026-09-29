"""organizations: AD code no longer unique (group companies share one, e.g. Earthman / Earthstar 0511029)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-28
"""
from alembic import op

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index('ix_organizations_ad_code')
        batch_op.create_index('ix_organizations_ad_code', ['ad_code'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index('ix_organizations_ad_code')
        batch_op.create_index('ix_organizations_ad_code', ['ad_code'], unique=True)

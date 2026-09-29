"""agency and examination charged per container

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

# Client: Agency and Examination are billed per container: (rate x containers) + GST
PER_CONTAINER = ("AC", "EC")


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE charge_master_entries SET calculation_basis='PER_CONTAINER' WHERE code IN :codes")
        .bindparams(sa.bindparam("codes", expanding=True)), {"codes": list(PER_CONTAINER)})


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE charge_master_entries SET calculation_basis='FLAT' WHERE code IN :codes")
        .bindparams(sa.bindparam("codes", expanding=True)), {"codes": list(PER_CONTAINER)})

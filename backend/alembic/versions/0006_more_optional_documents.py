"""more optional checklist documents

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

# Client: not needed on every shipment (CFS isn't paid for every client;
# HSS/Stamp Duty, FTA COO, Insurance, HBL only when applicable)
OPTIONAL = ("INSURANCE", "HBL_COPY", "HSS_AGREEMENT", "STAMP_DUTY", "FTA_CERTIFICATE_OF_ORIGIN",
            "CFS_PROFORMA_INVOICE", "CFS_TAX_INVOICE")


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE required_documents SET optional=1 WHERE document_type IN :types").bindparams(
            sa.bindparam("types", expanding=True)),
        {"types": list(OPTIONAL)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE required_documents SET optional=0 WHERE document_type IN :types").bindparams(
            sa.bindparam("types", expanding=True)),
        {"types": list(OPTIONAL)},
    )

"""shipment_documents.pdf_kind — digital / partly / scanned / unreadable

Existing documents are filled in by scripts/backfill_pdf_kind.py (needs the files).

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shipment_documents") as b:
        b.add_column(sa.Column("pdf_kind", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("shipment_documents") as b:
        b.drop_column("pdf_kind")

"""Commercial Invoice on every shipment's checklist (required) — client, 2026-09-29

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    for (hs_id,) in conn.execute(sa.text("SELECT id FROM hs_codes")).fetchall():
        if not conn.execute(sa.text("SELECT 1 FROM required_documents WHERE hs_code_id=:h AND document_type='COMMERCIAL_INVOICE'"),
                            {"h": hs_id}).first():
            conn.execute(sa.text("INSERT INTO required_documents (hs_code_id, document_type, optional) "
                                 "VALUES (:h, 'COMMERCIAL_INVOICE', FALSE)"), {"h": hs_id})


def downgrade() -> None:
    op.execute("DELETE FROM required_documents WHERE document_type='COMMERCIAL_INVOICE'")

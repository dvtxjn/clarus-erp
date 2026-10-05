"""shipment_documents.drive_folder_id: a Drive folder chosen at save time instead of the shipment's (client, 2026-10-05)

Documents are saved only into the shipment's linked Drive folder (or this one); the ERP no longer makes folders.
Invoices go into the shipment's linked folder too (else CLARUS ERP/Proforma Invoices/<client>).

Everything the ERP saved earlier into "CLARUS ERP - System" is marked pending, so the retry job saves a
copy in the right place (the old copies stay — the ERP can't delete; remove them by hand). Files a staff
member picked from Drive, or that the older sign-in path already put in the linked folder, are left alone.

Revision ID: 0051
Revises: 0050
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipment_documents", sa.Column("drive_folder_id", sa.String, nullable=True))
    conn = op.get_bind()
    docs = conn.execute(sa.text("SELECT id, extraction FROM shipment_documents WHERE drive_file_id IS NOT NULL "
                                "AND (drive_picked IS NULL OR drive_picked = :f)"), {"f": False}).fetchall()
    for doc_id, extraction in docs:
        if isinstance(extraction, str):
            extraction = json.loads(extraction or "{}")
        if (extraction or {}).get("saved_to_drive"):
            continue  # already in the shipment's folder (older per-user save)
        conn.execute(sa.text("UPDATE shipment_documents SET drive_sync_pending = :t WHERE id = :i"), {"t": True, "i": doc_id})
    conn.execute(sa.text("UPDATE stored_files SET drive_sync_pending = :t WHERE drive_file_id IS NOT NULL"), {"t": True})


def downgrade() -> None:
    op.drop_column("shipment_documents", "drive_folder_id")

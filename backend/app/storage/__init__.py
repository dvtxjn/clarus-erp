"""
Where files live (launch Phase 7).

Every file is written to the local disk first (the working copy the PDF readers use).
With STORAGE_BACKEND=drive the server also saves it in the client's Shared Drive:

    <the shipment's linked folder>/<generated name>.pdf      uploaded documents (never a folder the ERP made)
    System Documents/<generated name>.pdf                    buffer copy while a shipment has no linked folder
    <the shipment's linked folder>/<invoice file name>.pdf   a proforma when Sent, a final invoice when issued
    CLARUS ERP/Proforma Invoices/<client>/...                invoices of a shipment with no linked folder
                                                             (existing folder reused, never a duplicate)

Drive is then the lasting copy (a server's disk is wiped on redeploy): a missing local
file is fetched back from Drive when needed. A Drive failure never loses anything: the
file stays local, is marked pending, and `retry_pending` (every 5 minutes) saves it later.

Read and save only — the ERP never deletes anything in Drive (see drive_client.py).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.models.storage import DriveFolder, StoredFile
from app.storage.drive_client import DriveClient, DriveError

log = logging.getLogger("storage")

STORAGE_ROOT = Path(os.getenv("DOCUMENT_STORAGE_ROOT", "./storage/documents"))
PDF_ROOT = STORAGE_ROOT.parent / "generated"
REMOVED_PREFIX = "[removed] "


def backend() -> str:
    return os.getenv("STORAGE_BACKEND", "local").strip().lower()


def roots() -> dict[str, str]:
    return {"Documents": os.getenv("DRIVE_ROOT_FOLDER_ID", ""),
            "Invoices": os.getenv("DRIVE_INVOICES_FOLDER_ID", ""),
            "Backups": os.getenv("DRIVE_BACKUPS_FOLDER_ID", ""),
            "ERP": os.getenv("DRIVE_ERP_ROOT_ID", "")}  # the "CLARUS ERP" Shared Drive (client, 2026-10-05)


INVOICE_FALLBACK = "ERP/Proforma Invoices"


_client: Optional[DriveClient] = None


def drive() -> Optional[DriveClient]:
    """The Drive client, or None when storage is local."""
    global _client
    if backend() != "drive":
        return None
    if _client is None:
        _client = DriveClient(roots().values())
    return _client


def set_drive_client(client: Optional[DriveClient]) -> None:
    """Tests: plug in a fake Drive."""
    global _client
    _client = client


def clean(name: Optional[str], fallback: str = "_") -> str:
    """Safe Drive/disk name: no slashes, no control characters, not too long."""
    name = re.sub(r"[\x00-\x1f/\\]+", "-", (name or "").strip())[:120].strip(" .")
    return name or fallback


# --- folders: created once, even with simultaneous uploads ---

def ensure_folder(path: str) -> str:
    """Drive id of `path` ("Documents/SUNRISE TYRES/MEDU123"), creating missing folders.
    Each level is looked up / created in its own short transaction under an advisory
    lock, so two uploads for a new client end up in one folder."""
    client = drive()
    top, *rest = path.split("/")
    current = roots()[top]
    if not current:
        raise DriveError(f"No Drive folder configured for {top}")
    walked = top
    for name in rest:
        walked = f"{walked}/{name}"
        with SessionLocal() as s:
            row = s.query(DriveFolder).filter(DriveFolder.path == walked).first()
            if row is None:
                if engine.dialect.name == "postgresql":
                    s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"drive-folder:{walked}"})
                    row = s.query(DriveFolder).filter(DriveFolder.path == walked).first()  # made while we waited?
                if row is None:
                    fid = client.find_folder(current, name) or client.create_folder(current, name)
                    row = DriveFolder(path=walked, drive_id=fid)
                    s.add(row)
                    s.commit()
            current = row.drive_id
    return current


NO_FOLDER = ("No Drive folder linked to this shipment — kept safe in CLARUS ERP - System/Documents; "
             "link the folder and it is saved there.")


def push_document(doc, shipment) -> None:
    """Save the document's file in Drive (STORAGE_BACKEND=drive): only into the folder picked at save
    time or the shipment's linked folder — the ERP never makes folders (client, 2026-10-05). Unlinked:
    a buffer copy goes flat into CLARUS ERP - System/Documents and it stays pending until a folder is
    linked, then it is saved there (client, 2026-10-07). Never raises: a failure marks it pending. Caller commits."""
    client = drive()
    if client is None or doc.drive_picked:  # already in Drive: it was picked from there
        return
    folder = doc.drive_folder_id or shipment.drive_folder_id
    try:
        if not folder:  # nowhere to go yet: a buffer copy in the System drive (the disk is wiped on redeploy)
            if not doc.drive_file_id:
                meta = client.upload(roots()["Documents"], doc.generated_filename, Path(doc.file_path).read_bytes())
                doc.drive_file_id, doc.drive_link = meta["id"], meta.get("webViewLink")
            doc.drive_sync_pending, doc.drive_error = True, NO_FOLDER
            return
        data = Path(local_path(doc)).read_bytes()
        meta = client.upload(folder, doc.generated_filename, data, linked=True)
        doc.drive_file_id, doc.drive_link = meta["id"], meta.get("webViewLink")
        doc.drive_sync_pending, doc.drive_error = False, None
    except Exception as e:  # noqa: BLE001 — Drive/network trouble must never lose the upload
        log.warning("Drive save failed for document %s: %s", doc.id, e)
        doc.drive_sync_pending, doc.drive_error = True, str(e)[:300]


def mark_removed(doc, removed: bool) -> None:
    """Remove / restore in the app: only the Drive file's NAME changes ("[removed] …")."""
    client = drive()
    if client is None or not doc.drive_file_id or doc.drive_sync_pending or doc.drive_picked:
        return  # a staff member's own file is never touched
    name = f"{REMOVED_PREFIX}{doc.generated_filename}" if removed else doc.generated_filename
    try:
        client.rename(doc.drive_file_id, name, linked=True)  # a file the ERP saved itself
    except Exception as e:  # noqa: BLE001 — e.g. a file picked from someone's own Drive (outside the roots)
        log.info("Drive rename skipped for document %s: %s", doc.id, e)


def local_path(doc) -> str:
    """The document's file on this server's disk, fetched back from Drive if the disk
    was wiped (redeploy)."""
    p = Path(doc.file_path)
    if not p.exists():
        client = drive()
        if client is None or not doc.drive_file_id:
            raise FileNotFoundError(f"File for document {doc.id} is missing")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(client.download(doc.drive_file_id))
    return str(p)


# --- generated PDFs (proformas when Sent, final invoices when issued) ---

def save_pdf(db: Session, kind: str, ref_id: int, folder_path: str, name: str, data: bytes) -> StoredFile:
    """Keep a generated PDF: local copy + Drive. One per (kind, ref_id). Caller commits."""
    name = clean(name, f"{kind}-{ref_id}.pdf")
    local = PDF_ROOT / folder_path / name
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    sf = db.query(StoredFile).filter(StoredFile.kind == kind, StoredFile.ref_id == ref_id).first()
    if sf is None:
        sf = StoredFile(kind=kind, ref_id=ref_id, folder_path=folder_path, name=name, local_path=str(local))
        db.add(sf)
    elif sf.drive_file_id:
        return sf  # already saved in Drive: the first copy is the record, never replaced
    sf.folder_path, sf.name, sf.local_path = folder_path, name, str(local)
    _push_stored(sf)
    return sf


def _invoice_shipment(sf: StoredFile):
    """The shipment a generated invoice PDF belongs to."""
    from app.models.final_invoice import FinalInvoice
    from app.models.proforma import Proforma

    model = Proforma if sf.kind.startswith("proforma") else FinalInvoice
    with SessionLocal() as s:
        row = s.get(model, sf.ref_id)
        ship = row.shipment if row is not None else None
        return (ship.drive_folder_id, ship.client) if ship is not None else (None, None)


def _push_stored(sf: StoredFile) -> None:
    """Invoices go into the shipment's linked folder (client, 2026-10-05); with no linked
    folder, into CLARUS ERP/Proforma Invoices/<client> (looked up first, made only if absent)."""
    client = drive()
    if client is None:
        return
    try:
        p = Path(sf.local_path)
        if not p.exists() and sf.drive_file_id:  # disk wiped by a redeploy: fetch the saved copy
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(client.download(sf.drive_file_id))
        linked, client_name = _invoice_shipment(sf)
        if linked:
            meta = client.upload(linked, sf.name, p.read_bytes(), linked=True)
        else:
            meta = client.upload(ensure_folder(f"{INVOICE_FALLBACK}/{clean(client_name, 'No client')}"),
                                 sf.name, p.read_bytes())
        sf.drive_file_id, sf.drive_link = meta["id"], meta.get("webViewLink")
        sf.drive_sync_pending, sf.drive_error = False, None
    except Exception as e:  # noqa: BLE001
        log.warning("Drive save failed for %s %s: %s", sf.kind, sf.ref_id, e)
        sf.drive_sync_pending, sf.drive_error = True, str(e)[:300]


# --- the retry job ---

def retry_pending() -> int:
    """Save everything still pending in Drive. Returns how many are still pending."""
    from app.models.document import ShipmentDocument
    from app.models.shipment import Shipment

    if drive() is None:
        return 0
    with SessionLocal() as db:
        for doc in db.query(ShipmentDocument).filter(ShipmentDocument.drive_sync_pending.is_(True)).all():
            ship = db.get(Shipment, doc.shipment_id)
            if ship is not None:
                push_document(doc, ship)
        for sf in db.query(StoredFile).filter(StoredFile.drive_sync_pending.is_(True)).all():
            _push_stored(sf)
        db.commit()
        return (db.query(ShipmentDocument).filter(ShipmentDocument.drive_sync_pending.is_(True)).count()
                + db.query(StoredFile).filter(StoredFile.drive_sync_pending.is_(True)).count())

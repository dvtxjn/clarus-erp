"""
Folder reader (client, 2026-10-05): once a shipment's Drive folder is linked, every PDF
in it is read — what it is (file name, else first-page wording), attached to the
shipment and its details filled in, like an upload. Each file can be marked by hand as
any document type, or ignored; marks are kept and every re-scan respects them.

Drive is only read: nothing in the folder is moved, renamed, copied or deleted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import storage
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.enums import DocumentType, UserRole
from app.extraction.doc_type_guess import guess_from_content, guess_from_name
from app.extraction.cfs_totals import INVOICE_DOC_TYPES, RECEIPT_DOC_TYPES
from app.models.document import ShipmentDocument
from app.models.folder_mark import DriveFileMark
from app.models.user import User
from app.routers import documents as docs

router = APIRouter(prefix="/shipments/{shipment_id}/drive-folder", tags=["drive-folder"])

PDF_MIME = "application/pdf"
FOLDER_MIME = "application/vnd.google-apps.folder"
# Several of these can belong to one shipment; anything else is one per shipment, so the
# reader won't add a second one on its own (marking the file by hand still adds it).
MANY_ALLOWED = set(INVOICE_DOC_TYPES) | set(RECEIPT_DOC_TYPES) | {DocumentType.OTHER}


class MarkIn(BaseModel):
    document_type: Optional[str] = None  # a DocumentType value, "ignore", or None = back to the reader's guess
    file_name: Optional[str] = None


def _client():
    client = storage.drive()
    if client is None:
        raise HTTPException(status_code=400, detail="Reading the folder needs the server's Google Drive connection.")
    return client


def _folder_pdfs(client, folder_id: str, prefix: str = "", depth: int = 0) -> list[dict]:
    """PDFs in the folder and (two levels of) its sub-folders."""
    out = []
    for f in sorted(client.list_children(folder_id), key=lambda f: f.get("name", "").lower()):
        if f.get("mimeType") == FOLDER_MIME and depth < 2:
            out += _folder_pdfs(client, f["id"], f"{prefix}{f['name']}/", depth + 1)
        elif f.get("mimeType") == PDF_MIME or f.get("name", "").lower().endswith(".pdf"):
            out.append({"id": f["id"], "name": f"{prefix}{f['name']}"})
    return out


def _state(db: Session, shipment_id: int):
    marks = {m.drive_file_id: m for m in db.query(DriveFileMark).filter(DriveFileMark.shipment_id == shipment_id)}
    all_docs = (db.query(ShipmentDocument).execution_options(include_deleted=True)
                .filter(ShipmentDocument.shipment_id == shipment_id, ShipmentDocument.drive_file_id.isnot(None)).all())
    live = {d.drive_file_id: d for d in all_docs if d.deleted_at is None}
    removed = {d.drive_file_id: d for d in all_docs if d.deleted_at is not None and d.drive_file_id not in live}
    types_held = {d.document_type for d in db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == shipment_id)}
    return marks, live, removed, types_held


def _row(f: dict, mark: Optional[DriveFileMark], doc: Optional[ShipmentDocument], removed: Optional[ShipmentDocument],
         status: str, guess: Optional[DocumentType] = None) -> dict:
    guess = guess or guess_from_name(f["name"].rsplit("/", 1)[-1])
    return {
        "file_id": f["id"], "name": f["name"], "link": f"https://drive.google.com/file/d/{f['id']}/view",
        "guess": guess.value if guess else None,
        "mark": mark.document_type if mark else None,
        "status": status,
        "document_id": doc.id if doc else None,
        "document_type": doc.document_type.value if doc else (removed.document_type.value if removed else None),
    }


def _removed_after_mark(mark: Optional[DriveFileMark], removed: Optional[ShipmentDocument]) -> bool:
    """Taken off the shipment (Remove) after it was last marked: stays off until marked again."""
    return bool(removed and (mark is None or (mark.marked_at and mark.marked_at <= removed.deleted_at)))


@router.get("/files")
def folder_files(shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Every PDF in the folder and where it stands. Reads names only (quick)."""
    shipment = docs._get_shipment(db, shipment_id, current_user)
    if not shipment.drive_folder_id:
        raise HTTPException(status_code=400, detail="Link the shipment's Drive folder first.")
    files = _folder_pdfs(_client(), shipment.drive_folder_id)
    marks, live, removed, _ = _state(db, shipment.id)
    rows = []
    for f in files:
        mark, doc, gone = marks.get(f["id"]), live.get(f["id"]), removed.get(f["id"])
        if doc:
            status = "attached"
        elif mark and mark.document_type == DriveFileMark.IGNORE:
            status = "ignored"
        elif _removed_after_mark(mark, gone):
            status = "removed"
        else:
            status = "not_attached"
        rows.append(_row(f, mark, doc, gone, status))
    return rows


@router.post("/sync")
def sync_folder(shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Read the folder and attach what's not attached yet (marks first, then the reader's
    guess). Files already attached as something else than their mark are re-filed and read
    again. Returns every file's status plus the shipment details that were filled in."""
    shipment = docs._get_shipment(db, shipment_id, current_user)
    if not shipment.drive_folder_id:
        raise HTTPException(status_code=400, detail="Link the shipment's Drive folder first.")
    client = _client()
    files = _folder_pdfs(client, shipment.drive_folder_id)
    rows, updated, notes = [], [], []
    for f in files:
        marks, live, removed, types_held = _state(db, shipment.id)  # fresh: each add changes them
        mark, doc, gone = marks.get(f["id"]), live.get(f["id"]), removed.get(f["id"])
        marked = mark.document_type if mark else None
        if marked == DriveFileMark.IGNORE:
            rows.append(_row(f, mark, doc, gone, "attached" if doc else "ignored"))
            continue
        if doc:
            if marked and marked != doc.document_type.value:  # re-marked: re-file it and read it again
                storage.local_path(doc)  # this server's copy (fetched back if the disk was wiped)
                docs._refile(doc, shipment, DocumentType(marked))
                db.commit()
                doc = docs.reread_document(shipment.id, doc.id, db, current_user)
                updated += (doc.extraction or {}).get("updated") or []
            rows.append(_row(f, mark, doc, gone, "attached"))
            continue
        if _removed_after_mark(mark, gone):
            rows.append(_row(f, mark, None, gone, "removed"))
            continue
        doc_type = DocumentType(marked) if marked else guess_from_name(f["name"].rsplit("/", 1)[-1])
        data = None
        try:
            if doc_type is None:
                data = client.download(f["id"])
                doc_type = guess_from_content(data)
            if doc_type is None:
                rows.append(_row(f, mark, None, gone, "unrecognised"))
                continue
            if not marked and doc_type in types_held and doc_type not in MANY_ALLOWED:
                rows.append(_row(f, mark, None, gone, "duplicate", doc_type))
                continue
            if data is None:
                data = client.download(f["id"])
        except Exception as e:  # noqa: BLE001 — one unreadable file never stops the rest
            rows.append({**_row(f, mark, None, gone, "error", doc_type), "error": str(e)[:200]})
            continue
        new = docs._store_document(db, shipment, doc_type, f["name"].rsplit("/", 1)[-1],
                                   lambda out, d=data: out.write(d), current_user,
                                   drive_file_id=f["id"], drive_link=f"https://drive.google.com/file/d/{f['id']}/view")
        updated += (new.extraction or {}).get("updated") or []
        notes += (new.extraction or {}).get("notes") or []
        rows.append(_row(f, mark, new, gone, "added", doc_type))
    return {"files": rows, "updated": sorted(set(map(str, updated))), "notes": notes}


@router.put("/marks/{file_id}")
def mark_file(shipment_id: int, file_id: str, payload: MarkIn, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    """Mark a folder file as a document type, ignore it, or (None) hand it back to the reader.
    Ignoring a file that's already attached takes the document off the shipment — admin only,
    like Remove (soft delete; the Drive file is never touched)."""
    shipment = docs._get_shipment(db, shipment_id, current_user)
    value = payload.document_type
    if value not in (None, DriveFileMark.IGNORE) and value not in {t.value for t in DocumentType}:
        raise HTTPException(status_code=400, detail="Unknown document type")
    _, live, _, _ = _state(db, shipment.id)
    doc = live.get(file_id)
    if value == DriveFileMark.IGNORE and doc:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Only the admin can take an attached document off the shipment.")
        docs.remove_document(shipment.id, doc.id, db, current_user)
    mark = db.query(DriveFileMark).filter(DriveFileMark.shipment_id == shipment.id,
                                          DriveFileMark.drive_file_id == file_id).first()
    if value is None:
        if mark:
            db.delete(mark)  # our own setting row, not a document — nothing is lost
    else:
        if not mark:
            mark = DriveFileMark(shipment_id=shipment.id, drive_file_id=file_id)
            db.add(mark)
        mark.document_type, mark.file_name = value, payload.file_name or mark.file_name
        mark.marked_by_id, mark.marked_at = current_user.id, datetime.now()
    db.commit()
    return {"file_id": file_id, "mark": value}

import os
import re
import shutil
from pathlib import Path

from typing import BinaryIO, Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from urllib.parse import quote
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.audit import record_change
from app.core.deps import get_current_user, get_user_allowed_ports, require_admin
from app.core.locking import locked_shipment_or_404
from app import storage
from app.integrations import google_drive
from app.storage.drive_client import DriveError
from decimal import Decimal

from app.core.enums import DocumentType
from app.models.shipment import Shipment
from app.models.document import ShipmentDocument
from app.models.soft_delete import soft_delete
from app.models.user import User
from app.schemas.document import ShipmentDocumentOut, DocumentChecklistItem, InvoiceAmountsIn, CostInclusionIn
from app.invoice.autofill import refresh_draft_proformas
from app.extraction.cfs_totals import (
    INVOICE_DOC_TYPES, LINE_DOC_TYPES, RECEIPT_DOC_TYPES, cost_from_charges, default_cost_inclusion, invoice_charges, recompute_invoice_totals,
)
from app.extraction.naming import generate_document_filename
from app.extraction.document_extract import extract_document_fields
from app.extraction.pdf_kind import pdf_kind
from app.extraction.tracker_sync import apply_tracker_sync

router = APIRouter(prefix="/shipments/{shipment_id}/documents", tags=["documents"])

# Files that bundle several checklist documents together
COMBINED_DOCUMENTS = {
    DocumentType.DO_EMPTY_LETTER: (DocumentType.DO_LETTER, DocumentType.EMPTY_LETTER),
}

STORAGE_ROOT = storage.STORAGE_ROOT


@router.post("", response_model=ShipmentDocumentOut, status_code=201)
async def upload_document(
    shipment_id: int,
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    drive_access_token: Optional[str] = Form(None),  # to also save into the shipment's Drive folder
    save_to_folder_id: Optional[str] = Form(None),  # a different Drive folder, picked at save time
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Spec §2 (Document Manager): upload + tag in one step. Auto-renames per
    §3.2, stores the file, and triggers the tracker auto-update per §3.3
    (e.g. tagging OOC Bill of Entry -> ooc=True, status -> OOC_DONE).

    BE-type and CFS-invoice PDFs are read (extraction/document_extract.py)
    and the shipment is updated from them; the response's `extraction`
    says what was read, what changed, and any mismatches.
    """
    shipment = _get_shipment(db, shipment_id, current_user)
    if save_to_folder_id and not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", save_to_folder_id):
        raise HTTPException(status_code=422, detail="That isn't a Google Drive folder.")
    doc = _store_document(db, shipment, document_type, file.filename or "upload.pdf",
                          lambda out: shutil.copyfileobj(file.file, out), current_user,
                          drive_folder_id=save_to_folder_id or None)
    if shipment.drive_folder_id and storage.drive() is None:
        # no server-side Drive: the older per-shipment folder save (user's own Google token)
        await _save_to_drive_folder(db, shipment, doc, drive_access_token)
    return doc


async def _save_to_drive_folder(db: Session, shipment: Shipment, doc: ShipmentDocument, token: Optional[str]) -> None:
    """Copy the (renamed) upload into the shipment's linked Drive folder. A Drive
    failure never loses the upload — it's reported in the document's notes."""
    extraction = dict(doc.extraction or {})
    notes = list(extraction.get("notes", []))
    if not token:
        notes.append("Not saved to the shipment's Drive folder — Google Drive isn't connected.")
    else:
        try:
            with open(doc.file_path, "rb") as f:
                file_id, link = await google_drive.upload_pdf(
                    shipment.drive_folder_id, doc.generated_filename, f.read(), token)
            doc.drive_file_id, doc.drive_link = file_id, link
            extraction["saved_to_drive"] = True
        except google_drive.DriveError as e:
            notes.append(str(e))
        except httpx.HTTPError:
            notes.append("Couldn't reach Google Drive — the file is saved here but not in the Drive folder.")
    extraction["notes"] = notes
    doc.extraction = extraction
    db.commit()
    db.refresh(doc)


class DriveDocumentIn(BaseModel):
    document_type: DocumentType
    file_id: str
    access_token: Optional[str] = None  # user's short-lived Google token; without it the server's own Drive reads the file


def _fetch_with_server_drive(file_id: str) -> google_drive.DriveFile:
    """Read a PDF through the server's own Drive connection (read only)."""
    client = storage.drive()
    if client is None:
        raise google_drive.DriveError("Sign in to Google Drive to pick files (the server has no Drive connection).")
    try:
        info = client.get(file_id, "id,name,mimeType,size,webViewLink")
    except DriveError:
        raise google_drive.DriveError("File not found in Google Drive (or the ERP can't see it).")
    name = info.get("name") or "drive.pdf"
    if info.get("mimeType") != "application/pdf":
        raise google_drive.DriveError(f"'{name}' isn't a PDF — pick the PDF copy of the document.")
    if int(info.get("size") or 0) > google_drive.MAX_BYTES:
        raise google_drive.DriveError(f"'{name}' is larger than 25 MB.")
    try:
        data = client.download(file_id)
    except DriveError:
        raise google_drive.DriveError(f"Couldn't read '{name}' from Google Drive — try again.")
    if len(data) > google_drive.MAX_BYTES:
        raise google_drive.DriveError(f"'{name}' is larger than 25 MB.")
    return google_drive.DriveFile(file_id=file_id, name=name, web_link=info.get("webViewLink"), content=data)


@router.post("/from-drive", response_model=ShipmentDocumentOut, status_code=201)
async def add_document_from_drive(
    shipment_id: int,
    payload: DriveDocumentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Same as an upload, but the PDF is one the user picked in Google Drive.
    A copy is stored and processed like an upload; the Drive link is kept."""
    shipment = _get_shipment(db, shipment_id, current_user)
    try:
        if payload.access_token:
            drive_file = await google_drive.fetch_drive_pdf(payload.file_id, payload.access_token)
        else:
            drive_file = await run_in_threadpool(_fetch_with_server_drive, payload.file_id)
    except google_drive.DriveError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Couldn't reach Google Drive — try again.")
    return _store_document(db, shipment, payload.document_type, drive_file.name,
                           lambda out: out.write(drive_file.content), current_user,
                           drive_file_id=drive_file.file_id, drive_link=drive_file.web_link)


@router.post("/{document_id}/reread", response_model=ShipmentDocumentOut)
def reread_document(shipment_id: int, document_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """Read an already-uploaded document again (e.g. after the reader was
    improved) and apply what it finds to the shipment, same as on upload."""
    shipment = _get_shipment(db, shipment_id, current_user)
    doc = db.query(ShipmentDocument).filter(ShipmentDocument.id == document_id,
                                            ShipmentDocument.shipment_id == shipment.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = storage.local_path(doc)
    fields = extract_document_fields(doc.document_type, path)  # slow part, before the lock
    kind = pdf_kind(path)
    shipment = locked_shipment_or_404(db, shipment_id)
    doc.pdf_kind = kind
    doc.tracker_sync_applied = False
    doc.extraction = {"fields": fields}  # totals need its invoice number (duplicates count once)
    result = apply_tracker_sync(db, shipment, doc, current_user.id, fields)
    doc.extraction = {"fields": fields, **result, "duplicate_of": (doc.extraction or {}).get("duplicate_of")}
    refresh_draft_proformas(db, shipment)  # draft proformas pick up the new figures
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{document_id}", status_code=204)
def remove_document(shipment_id: int, document_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(require_admin)):
    """Take a document off the shipment (admin only — spec §2.4). Soft delete: the
    record stays (restorable from Recently deleted) and the file is moved to
    <storage>/_removed/<shipment id>/ so a new upload can't overwrite it. Recorded in
    the change history. Shipment fields it filled in stay as they are. A copy saved in
    Google Drive is not touched."""
    _get_shipment(db, shipment_id, current_user)
    shipment = locked_shipment_or_404(db, shipment_id)
    doc = db.query(ShipmentDocument).filter(ShipmentDocument.id == document_id,
                                            ShipmentDocument.shipment_id == shipment.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    src = Path(doc.file_path)
    if src.exists():
        removed_dir = STORAGE_ROOT / "_removed" / str(shipment.id)
        removed_dir.mkdir(parents=True, exist_ok=True)
        dest = removed_dir / f"{doc.id} - {src.name}"
        shutil.move(str(src), dest)
        doc.file_path = str(dest)
    record_change(db, "shipment_documents", doc.id, "removed",
                  f"{doc.document_type.value}: {doc.generated_filename}", None, current_user.id)
    was_invoice = doc.document_type in INVOICE_DOC_TYPES
    soft_delete(db, doc, current_user.id)
    storage.mark_removed(doc, True)  # Drive: renamed "[removed] …", never deleted
    if was_invoice:  # CFS / shipping line totals are sums of the remaining invoices
        recompute_invoice_totals(db, shipment, current_user.id)
    refresh_draft_proformas(db, shipment)
    db.commit()


@router.patch("/{document_id}/amounts", response_model=ShipmentDocumentOut)
def correct_invoice_amounts(shipment_id: int, document_id: int, payload: InvoiceAmountsIn,
                            db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fix a misread CFS / shipping line invoice. Total = before-tax + GST; the
    shipment's totals (and CFS payment after TDS) are recalculated. Hand-corrected figures are
    kept even if the document is re-read later."""
    _get_shipment(db, shipment_id, current_user)
    shipment = locked_shipment_or_404(db, shipment_id)
    doc = db.query(ShipmentDocument).filter(ShipmentDocument.id == document_id,
                                            ShipmentDocument.shipment_id == shipment.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.document_type not in INVOICE_DOC_TYPES + RECEIPT_DOC_TYPES + (DocumentType.STAMP_DUTY,):
        raise HTTPException(status_code=400, detail="Only CFS / shipping line invoices, receipts and stamp duty have amounts to correct")
    new = {"amount_before_tax": payload.amount_before_tax, "gst_amount": payload.gst_amount,
           "amount_total": payload.amount_before_tax + payload.gst_amount}
    for field, value in new.items():
        if getattr(doc, field) != value:
            record_change(db, "shipment_documents", doc.id, field, getattr(doc, field), value, current_user.id)
            setattr(doc, field, value)
    doc.amounts_edited = True
    recompute_invoice_totals(db, shipment, current_user.id)
    refresh_draft_proformas(db, shipment)
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/{document_id}/cost-inclusion", response_model=ShipmentDocumentOut)
def set_cost_inclusion(shipment_id: int, document_id: int, payload: CostInclusionIn,
                       db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Which part of a shipping line invoice is the proforma's cost inclusion:
    tick charge lines in/out, type the figure by hand, or reset to the rule."""
    _get_shipment(db, shipment_id, current_user)
    shipment = locked_shipment_or_404(db, shipment_id)
    doc = db.query(ShipmentDocument).filter(ShipmentDocument.id == document_id,
                                            ShipmentDocument.shipment_id == shipment.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.document_type not in LINE_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Only shipping line invoices have a cost inclusion")
    before = (doc.cost_before_tax, doc.cost_gst, doc.cost_excluded, doc.cost_manual)
    if payload.reset:
        doc.cost_manual = False
        default_cost_inclusion(doc)
    elif payload.before_tax is not None:
        doc.cost_before_tax, doc.cost_gst = payload.before_tax, payload.gst or Decimal("0")
        doc.cost_excluded, doc.cost_manual = None, True
    elif payload.excluded is not None:
        n = len(invoice_charges(doc))
        if not n:
            raise HTTPException(status_code=400, detail="No charge lines were read from this invoice — type the figure instead")
        excluded = sorted({i for i in payload.excluded if 0 <= i < n})
        doc.cost_excluded, doc.cost_manual = excluded or None, False
        doc.cost_before_tax, doc.cost_gst = cost_from_charges(doc, excluded) if excluded else (None, None)
    else:
        raise HTTPException(status_code=400, detail="Send excluded, before_tax + gst, or reset")
    after = (doc.cost_before_tax, doc.cost_gst, doc.cost_excluded, doc.cost_manual)
    if after != before:
        record_change(db, "shipment_documents", doc.id, "cost_inclusion", str(before), str(after), current_user.id)
    recompute_invoice_totals(db, shipment, current_user.id)
    refresh_draft_proformas(db, shipment)
    db.commit()
    db.refresh(doc)
    return doc


def _refile(doc: ShipmentDocument, shipment: Shipment, new_type: DocumentType) -> str:
    """Change a stored document's type and rename its file to match."""
    base = generate_document_filename(new_type, shipment.hbl or shipment.mbl, shipment.be_no)
    folder = Path(doc.file_path).parent
    name, i = f"{base}.pdf", 2
    while (folder / name).exists():
        name, i = f"{base} ({i}).pdf", i + 1
    new_path = folder / name
    shutil.move(doc.file_path, new_path)
    doc.document_type, doc.generated_filename, doc.file_path = new_type, name, str(new_path)
    return name


def _get_shipment(db: Session, shipment_id: int, user: User) -> Shipment:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    allowed = get_user_allowed_ports(user)
    if allowed is not None and shipment.port not in allowed:
        raise HTTPException(status_code=403, detail="Not permitted to access this shipment")
    return shipment


def _store_document(db: Session, shipment: Shipment, document_type: DocumentType, original_filename: str,
                    write: Callable[[BinaryIO], object], user: User,
                    drive_file_id: Optional[str] = None, drive_link: Optional[str] = None,
                    drive_folder_id: Optional[str] = None) -> ShipmentDocument:
    """Name + save the file, read it, update the shipment, record the document."""
    bl_number = shipment.hbl or shipment.mbl
    base_name = generate_document_filename(document_type, bl_number, shipment.be_no)
    generated_filename = f"{base_name}.pdf"

    shipment_dir = STORAGE_ROOT / str(shipment.id)
    shipment_dir.mkdir(parents=True, exist_ok=True)
    dest_path = shipment_dir / generated_filename

    # If a file with this exact generated name already exists, suffix it
    # rather than silently overwriting — mirrors the reference tool's
    # duplicate-output-path detection (spec §5.3).
    if dest_path.exists():
        i = 2
        while (shipment_dir / f"{base_name} ({i}).pdf").exists():
            i += 1
        generated_filename = f"{base_name} ({i}).pdf"
        dest_path = shipment_dir / generated_filename

    with dest_path.open("wb") as out_file:
        write(out_file)
    # Read the PDF (BE / OOC / CFS invoice fields) before locking — it's the slow part
    fields = extract_document_fields(document_type, str(dest_path))
    kind = pdf_kind(str(dest_path))  # digital or scanned

    # One short locked transaction: fresh shipment row, "fill blanks only" is judged on it
    shipment = locked_shipment_or_404(db, shipment.id)
    doc = ShipmentDocument(
        shipment_id=shipment.id,
        document_type=document_type,
        original_filename=original_filename,
        generated_filename=generated_filename,
        file_path=str(dest_path),
        uploaded_by_id=user.id,
        drive_file_id=drive_file_id,
        drive_link=drive_link,
        drive_folder_id=drive_folder_id,
        drive_picked=drive_file_id is not None,
        pdf_kind=kind,
    )
    db.add(doc)
    db.flush()  # get doc.id without committing yet

    refiled = None
    if document_type == DocumentType.ASSESSED_BILL_OF_ENTRY and fields.get("is_ooc_copy"):
        # It's actually the OOC copy: file it as one (type + file name)
        refiled = _refile(doc, shipment, DocumentType.OOC_BILL_OF_ENTRY)
    doc.extraction = {"fields": fields}  # totals need its invoice number (duplicates count once)
    result = apply_tracker_sync(db, shipment, doc, user.id, fields)
    if refiled:
        result["notes"].insert(0, "This is an OOC copy — filed as OOC Bill of Entry.")
    duplicate_of = (doc.extraction or {}).get("duplicate_of")
    if duplicate_of:
        result["notes"].insert(0, f"Same invoice ({fields.get('invoice_no') or 'same IRN'}) was already added — "
                                  "its amounts are counted once.")
    doc.extraction = {"fields": fields, **result, "duplicate_of": duplicate_of}
    refresh_draft_proformas(db, shipment)  # draft proformas pick up the new figures

    db.commit()  # ends the locked part
    # Save the lasting copy in the Shared Drive (STORAGE_BACKEND=drive), outside the lock;
    # a Drive failure only marks it pending for the retry job
    storage.push_document(doc, shipment)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/file")
def view_document_file(shipment_id: int, document_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """The stored PDF itself (opens in the browser). Fetched back from Drive if this
    server's disk no longer has it."""
    shipment = _get_shipment(db, shipment_id, current_user)
    doc = db.query(ShipmentDocument).filter(ShipmentDocument.id == document_id,
                                            ShipmentDocument.shipment_id == shipment.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        path = storage.local_path(doc)
    except (FileNotFoundError, storage.DriveError):
        raise HTTPException(status_code=404, detail="The file isn't available — upload it again.")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(doc.generated_filename)}"})


@router.get("", response_model=list[ShipmentDocumentOut])
def list_documents(shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == shipment_id).all()


@router.get("/checklist", response_model=list[DocumentChecklistItem])
def get_document_checklist(
    shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """
    Spec §3.1: when a shipment is tagged with an HS code, its required-doc
    checklist auto-populates in the Document Manager. Required rows come
    from the shipment's HS code (if any is assigned); every other uploaded
    document still shows up so nothing uploaded is ever hidden.
    """
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    uploaded = db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == shipment_id).all()
    uploaded_by_type: dict = {}
    for doc in sorted(uploaded, key=lambda d: d.id):
        uploaded_by_type.setdefault(doc.document_type, []).append(doc)

    required_docs = shipment.hs_code.required_documents if shipment.hs_code else []
    required_types = [rd.document_type for rd in required_docs]

    # A combined file counts for each document it contains.
    covered_by = {t: list(docs) for t, docs in uploaded_by_type.items()}
    for combined, parts in COMBINED_DOCUMENTS.items():
        for part in parts:
            covered_by.setdefault(part, []).extend(uploaded_by_type.get(combined, []))

    rows = [
        DocumentChecklistItem(
            document_type=rd.document_type,
            required=True,
            optional=rd.optional and not (
                shipment.cfs_paid_by_us and rd.document_type == DocumentType.CFS_TAX_INVOICE
            ),
            uploaded=bool(covered_by.get(rd.document_type)),
            document=(covered_by.get(rd.document_type) or [None])[0],
            documents=covered_by.get(rd.document_type, []),
        )
        for rd in required_docs
    ]
    shown = {d.id for r in rows for d in r.documents}
    # Anything uploaded outside the required set (e.g. "other") still shows.
    for doc_type, docs in uploaded_by_type.items():
        extra = [d for d in docs if d.id not in shown]
        if doc_type not in required_types and extra:
            rows.append(DocumentChecklistItem(document_type=doc_type, required=False, uploaded=True,
                                              document=extra[0], documents=extra))
    return rows

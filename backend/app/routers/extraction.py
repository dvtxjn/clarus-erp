"""
Module 3 extraction endpoints (spec §5.1 / §5.1a). Stateless: they return
what was read from the uploaded files; nothing is written to shipments or
proformas here — the batch fee-entry screen decides what to save.
"""
import io
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.extraction.batch import scan_batch
from app.extraction.excel_imports import load_challan_due_amounts, load_org_details
from app.models.organization import OrganizationEntry
from app.models.soft_delete import soft_delete
from app.models.shipment import Shipment
from app.models.user import User
from app.schemas.extraction import (
    BatchScanOut, ChallanOut, OrganizationBase, OrganizationOut, OrgImportOut,
)

# Every route here is invoicing: admin-only, including reads (see require_billing_access)
router = APIRouter(tags=["extraction"], dependencies=[Depends(require_billing_access)])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def _read(upload: UploadFile) -> io.BytesIO:
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{upload.filename} is larger than 25 MB")
    return io.BytesIO(data)


@router.post("/extraction/scan", response_model=BatchScanOut)
async def scan_pdfs(files: List[UploadFile] = File(...), db: Session = Depends(get_db),
                    _user: User = Depends(require_billing_access)):
    """Upload any mix of Bill of Entry and CFS invoice PDFs."""
    streams = [(f.filename or "upload.pdf", await _read(f)) for f in files]
    registry = {o.ad_code: o.name for o in db.query(OrganizationEntry).filter(OrganizationEntry.is_active)}
    existing = {be: sid for sid, be in db.query(Shipment.id, Shipment.be_no).filter(Shipment.be_no.isnot(None))}
    return scan_batch(streams, registry, existing)


@router.post("/extraction/challan", response_model=ChallanOut)
async def parse_challan(file: UploadFile = File(...), _user: User = Depends(require_billing_access)):
    """Daily duty challan export -> {BE number: Due Amount}."""
    due, note = load_challan_due_amounts(await _read(file))
    if not due and note:
        raise HTTPException(status_code=400, detail=note)
    return ChallanOut(due_amounts=due, note=note)


# --- Organization repository (AD Code -> registered name) ---

@router.get("/organizations", response_model=List[OrganizationOut])
def list_organizations(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    return db.query(OrganizationEntry).order_by(OrganizationEntry.name).all()


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(payload: OrganizationBase, db: Session = Depends(get_db),
                        _user: User = Depends(require_billing_access)):
    payload = _clean_org(payload)
    _check_org(payload, None)
    clash = name_taken(db, payload.name, None)
    if clash:
        raise HTTPException(status_code=400, detail=f"Already in the list as “{clash.name}”")
    org = OrganizationEntry(**payload.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.put("/organizations/{org_id}", response_model=OrganizationOut)
def update_organization(org_id: int, payload: OrganizationBase, db: Session = Depends(get_db),
                        _user: User = Depends(require_billing_access)):
    payload = _clean_org(payload)
    org = db.get(OrganizationEntry, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    _check_org(payload, org)
    clash = name_taken(db, payload.name, org_id)
    if clash:
        raise HTTPException(status_code=400, detail=f"Another organization is already called “{clash.name}”")
    for k, v in payload.model_dump().items():
        setattr(org, k, v)
    db.commit()
    db.refresh(org)
    return org


GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
IEC_RE = re.compile(r"^[A-Z0-9]{10}$")


def name_taken(db: Session, name: str, org_id: Optional[int]) -> Optional[OrganizationEntry]:
    """Same name once case, punctuation and 'Private Limited' / 'Pvt Ltd' are ignored."""
    from app.invoice.build import _norm
    key = _norm(name)
    return next((o for o in db.query(OrganizationEntry) if o.id != org_id and _norm(o.name) == key), None)


def _check_org(p: OrganizationBase, org: Optional[OrganizationEntry]) -> None:
    """GSTIN / PAN / IEC formats — only the ones being changed, so old data doesn't block an edit."""
    def changed(f):
        v = getattr(p, f)
        return v and (org is None or v != getattr(org, f))
    if changed("gstin") and not GSTIN_RE.match(p.gstin):
        raise HTTPException(status_code=422, detail=f"GSTIN “{p.gstin}” isn't valid — 15 characters, e.g. 24AAACC1234F1Z5")
    if changed("pan") and not PAN_RE.match(p.pan):
        raise HTTPException(status_code=422, detail=f"PAN “{p.pan}” isn't valid — e.g. AAACC1234F")
    if changed("iec") and not IEC_RE.match(p.iec):
        raise HTTPException(status_code=422, detail=f"IEC “{p.iec}” should be 10 letters / digits")
    if (changed("gstin") or changed("pan")) and p.gstin and p.pan and GSTIN_RE.match(p.gstin) \
            and p.gstin[2:12] != p.pan:
        raise HTTPException(status_code=422, detail="The PAN doesn't match the GSTIN (characters 3–12)")


def _clean_org(payload: OrganizationBase) -> OrganizationBase:
    """Blank strings -> None; GSTIN / PAN upper-case."""
    data = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in payload.model_dump().items()}
    for k in ("gstin", "pan", "iec"):
        if data.get(k):
            data[k] = data[k].upper()
    data["name"] = data["name"] or payload.name
    return OrganizationBase(**data)


@router.delete("/organizations/{org_id}", status_code=204)
def delete_organization(org_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    org = db.get(OrganizationEntry, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    soft_delete(db, org, _admin.id)  # the admin can restore it from Recently deleted
    db.commit()


@router.post("/organizations/import", response_model=OrgImportOut)
async def import_organizations(file: UploadFile = File(...), db: Session = Depends(get_db),
                               _admin: User = Depends(require_admin)):
    """Bulk upsert from the filing software's 'Organization List' .xlsx export."""
    try:
        entries = load_org_details(await _read(file))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't read file: {e}")
    if not entries:
        raise HTTPException(status_code=400, detail="No 'Organization List' sheet with an 'Organization' column found")
    from app.invoice.build import _norm
    by_name = {_norm(o.name): o for o in db.query(OrganizationEntry)}
    created = updated = 0
    for details in entries:  # matched by name: an AD code can be shared by group companies
        org = by_name.get(_norm(details["name"]))
        if org is None:
            org = OrganizationEntry(**details)
            db.add(org)
            by_name[_norm(org.name)] = org
            created += 1
            continue
        for k, v in details.items():
            if v is not None and v != "" and getattr(org, k) != v:
                setattr(org, k, v)  # never blank out details typed in by hand
        updated += 1
    db.commit()
    return OrgImportOut(created=created, updated=updated)

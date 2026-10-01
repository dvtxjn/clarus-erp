"""
Duty challans (daily ICEGATE pending-challan list) -> customs duty interest
on proformas. Uploaded from the dashboard every day; a BE's figure is its most
recent row, matched to shipments by BE number (+ BE date when known) whenever a proforma is filled
or viewed. Interest = Due Amount - the BE's total duty.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.core.locking import lock_shipments
from app.extraction.excel_imports import challan_list_time, load_challan_rows
from app.core.enums import DocumentType
from app.models.challan import IST, DutyChallan, ist_day, today_ist
from app.models.document import ShipmentDocument
from app.models.organization import OrganizationEntry
from app.models.shipment import Shipment
from app.models.user import User

# Every route here is invoicing: admin-only, including reads (see require_billing_access)
router = APIRouter(tags=["duty challans"], dependencies=[Depends(require_billing_access)])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ChallanRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    be_no: str
    be_date: Optional[str] = None
    location_code: Optional[str] = None
    challan_no: Optional[str] = None
    due_amount: Decimal
    source: str
    filename: Optional[str] = None
    uploaded_at: datetime
    listed_at: Optional[datetime] = None


class ChallanMatch(BaseModel):
    be_no: str
    shipment_id: int
    job: Optional[str] = None
    mbl: str
    due_amount: Decimal
    interest: Optional[Decimal] = None  # None = shipment has no BE duty amount yet


class ChallanUploadOut(BaseModel):
    rows: int
    matched: list[ChallanMatch]
    unmatched: list[str]  # BE numbers with no shipment (yet)
    note: Optional[str] = None


class ChallanManual(BaseModel):
    be_no: str = Field(min_length=1, max_length=20)
    due_amount: Decimal = Field(ge=0)
    challan_no: Optional[str] = Field(default=None, max_length=40)


class AwaitingChallan(BaseModel):
    id: int
    job: Optional[str] = None
    mbl: str
    be_no: str


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _shown(dt: datetime) -> str:
    return _utc(dt).astimezone(IST).strftime("%d-%b %H:%M")


class DailyStatus(BaseModel):
    """Dashboard reminder: was today's challan list / org repository updated? Goes by when the list was
    made (ICEGATE's stamp in the file), not when it was uploaded."""
    challans_last_uploaded_at: Optional[datetime] = None
    challans_updated_today: bool
    challans_in_last_upload: int
    organizations: int
    organizations_last_updated_at: Optional[datetime] = None
    organizations_updated_today: bool
    # ongoing shipments with a BE but neither a duty challan nor an OOC copy: interest unknown
    awaiting_challan: list[AwaitingChallan] = []


def _match(db: Session, rows: list[tuple[str, Optional[str]]]) -> tuple[list[ChallanMatch], list[str]]:
    """rows = (BE no, the challan row's BE date text or None). BE numbers are reused every year (client,
    2026-09-30): a dated row matches the shipment with that BE date (or one with no BE date yet); an
    undated row falls back to the BE's most recent shipment."""
    from app.invoice.build import challan_be_date, latest_challan  # avoid an import cycle at load time

    ships: dict[str, list[Shipment]] = {}
    for s in db.query(Shipment).filter(Shipment.be_no.in_({be for be, _ in rows})):
        ships.setdefault(s.be_no, []).append(s)
    matched, unmatched, seen = [], [], set()
    for be, be_date in rows:
        cands = sorted(ships.get(be, []), key=lambda x: (x.be_dt is not None, x.be_dt or date.min, x.id), reverse=True)
        d = challan_be_date(be_date)
        if d is not None:
            cands = [x for x in cands if x.be_dt == d] or [x for x in cands if x.be_dt is None]
        if not cands:
            unmatched.append(be)
            continue
        s = cands[0]
        if s.id in seen:
            continue
        seen.add(s.id)
        ch = latest_challan(db, be, s.be_dt)
        if ch is None:  # only another year's challan on file
            unmatched.append(be)
            continue
        interest = (max(Decimal("0"), Decimal(ch.due_amount) - Decimal(s.duty_amount))
                    if s.duty_amount is not None else None)
        matched.append(ChallanMatch(be_no=be, shipment_id=s.id, job=s.job, mbl=s.mbl,
                                    due_amount=ch.due_amount, interest=interest))
    return matched, unmatched


def _refresh(db: Session, matched: list[ChallanMatch]) -> None:
    """New interest -> Customs Duty (and Nhava Sheva Stamp Duty) on draft proformas."""
    from app.invoice.autofill import refresh_draft_proformas
    for shipment in lock_shipments(db, (m.shipment_id for m in matched)):  # id order: no deadlocks
        refresh_draft_proformas(db, shipment)


@router.post("/duty-challans/upload", response_model=ChallanUploadOut)
async def upload_challans(file: UploadFile = File(...), db: Session = Depends(get_db),
                          user: User = Depends(require_billing_access)):
    """Today's duty challan list (.xlsx: IEC, Location Code, Doc type, Doc no.,
    Doc date, Challan no., Due Amount). Every row is kept with the upload time."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB")
    rows, note = load_challan_rows(io.BytesIO(data))
    if not rows:
        raise HTTPException(status_code=400, detail=note or "No BE rows found in this file.")
    now = datetime.now()  # one timestamp per upload = "rows in the last upload"
    listed = challan_list_time(io.BytesIO(data))
    notes = [note] if note else []
    if listed is None:
        listed = datetime.now(timezone.utc)
        notes.append("This file has no ICEGATE time in it — counted as a list made now.")
    else:
        listed = _utc(listed)
        made = {_utc(t) for (t,) in db.query(DutyChallan.listed_at)
                .filter(DutyChallan.source == "upload", DutyChallan.listed_at.isnot(None)).distinct()}
        if listed in made:
            raise HTTPException(status_code=409, detail=f"This list (made {_shown(listed)}) was already uploaded.")
        if ist_day(listed) != today_ist():
            notes.append(f"This list was made on {_shown(listed)} — not today's. Download today's from ICEGATE for current interest.")
        newer = max((t for t in made if t > listed), default=None)
        if newer:
            notes.append(f"A newer list (made {_shown(newer)}) is already in — this one doesn't replace its amounts.")
    for r in rows:
        db.add(DutyChallan(**r, source="upload", filename=file.filename, uploaded_by_id=user.id,
                           uploaded_at=now, listed_at=listed))
    note = " ".join(notes) or None
    db.flush()
    record_change(db, "duty_challans", 0, "upload", None, f"{file.filename}: {len(rows)} row(s)", user.id)
    matched, unmatched = _match(db, [(r["be_no"], r.get("be_date")) for r in rows])
    _refresh(db, matched)
    db.commit()
    return ChallanUploadOut(rows=len(rows), matched=matched, unmatched=unmatched, note=note)


@router.post("/duty-challans", response_model=ChallanUploadOut, status_code=201)
def add_challan(payload: ChallanManual, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """One BE's challan Due Amount entered by hand."""
    be = payload.be_no.strip()
    # dated with the BE's latest shipment (BE numbers are reused every year), so it isn't mistaken for
    # another year's figure and outranks older rows for this BE
    latest = (db.query(Shipment).filter(Shipment.be_no == be, Shipment.be_dt.isnot(None))
              .order_by(Shipment.be_dt.desc()).first())
    db.add(DutyChallan(be_no=be, be_date=latest.be_dt.strftime("%d.%m.%Y") if latest else None,
                       due_amount=payload.due_amount, challan_no=payload.challan_no,
                       source="manual", uploaded_by_id=user.id))
    db.flush()
    record_change(db, "duty_challans", 0, "manual", None, f"BE {be}: {payload.due_amount}", user.id)
    matched, unmatched = _match(db, [(be, latest.be_dt.strftime("%d.%m.%Y") if latest else None)])
    _refresh(db, matched)
    db.commit()
    return ChallanUploadOut(rows=1, matched=matched, unmatched=unmatched)


@router.get("/duty-challans", response_model=list[ChallanRowOut])
def list_challans(be_no: Optional[str] = None, db: Session = Depends(get_db),
                  _user: User = Depends(require_billing_access)):
    q = db.query(DutyChallan)
    if be_no:
        q = q.filter(DutyChallan.be_no == be_no.strip())
    return q.order_by(DutyChallan.listed_at.desc().nullslast(), DutyChallan.id.desc()).limit(200).all()


@router.delete("/duty-challans/{challan_id}", status_code=204)
def delete_challan(challan_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    ch = db.get(DutyChallan, challan_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Challan row not found")
    record_change(db, "duty_challans", ch.id, "deleted", f"BE {ch.be_no}: {ch.due_amount}", None, user.id)
    db.delete(ch)
    db.commit()


@router.get("/daily-updates", response_model=DailyStatus)
def daily_status(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    last = db.query(func.max(DutyChallan.listed_at)).scalar()
    in_last = db.query(DutyChallan).filter(DutyChallan.listed_at == last).count() if last else 0
    org_last = db.query(func.max(OrganizationEntry.updated_at)).scalar()
    with_challan = {be for (be,) in db.query(DutyChallan.be_no).distinct()}
    with_ooc = {sid for (sid,) in db.query(ShipmentDocument.shipment_id)
                .filter(ShipmentDocument.document_type == DocumentType.OOC_BILL_OF_ENTRY).distinct()}
    awaiting = [AwaitingChallan(id=s.id, job=s.job, mbl=s.mbl, be_no=s.be_no)
                for s in db.query(Shipment).filter(Shipment.be_no.isnot(None), Shipment.be_no != "",
                                                  Shipment.is_archived.is_(False))
                if not s.is_fully_cleared and s.be_no not in with_challan and s.id not in with_ooc]
    return DailyStatus(
        challans_last_uploaded_at=last,
        challans_updated_today=bool(last and ist_day(last) == today_ist()),
        challans_in_last_upload=in_last,
        organizations=db.query(OrganizationEntry).filter(OrganizationEntry.is_active.is_(True)).count(),
        organizations_last_updated_at=org_last,
        organizations_updated_today=bool(org_last and org_last.date() == date.today()),
        awaiting_challan=awaiting,
    )

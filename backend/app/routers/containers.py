"""
Containers of every shipment (client, 2026-09-30). The container list comes first from the sea IGM (all
shipments, sea ports and inland); for inland shipments the ICD BL status then adds each container's arrival
at the FPOD, where its free days start. At a sea port the free days start at the inward date (INW), so a
container there shows the INW as its arrival unless one is typed. Every change is audited, removal is a
soft delete.
"""
import re
from datetime import date, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import alerts, liners
from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import get_current_user, get_user_allowed_ports
from app.igm import icd
from app.models.container import ShipmentContainer
from app.models.shipment import Shipment
from app.models.soft_delete import soft_delete
from app.models.user import User

router = APIRouter(prefix="/shipments/{shipment_id}/containers", tags=["containers"])


class ContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    container_no: str
    status: Optional[str] = None
    arrival_date: Optional[date] = None
    arrival_status: Optional[str] = None
    tracking_status: Optional[str] = None
    source: str
    is_manual: bool
    arrival_from_inw: bool = False  # sea port, nothing typed: the shipment's inward date stands in
    # free days at the FPOD: day N counted from the arrival (arrival = day 1). free_days = this container's
    # free days (typed when it differs from the standard 14; free_days_typed), last_free_day = arrival + free_days - 1
    free_days: Optional[int] = None
    free_days_typed: bool = False
    day: Optional[int] = None
    last_free_day: Optional[date] = None
    days_left: Optional[int] = None


class ContainerIn(BaseModel):
    container_no: str = Field(min_length=4, max_length=20)
    status: Optional[str] = None
    arrival_date: Optional[date] = None


class ContainerPatch(BaseModel):
    container_no: Optional[str] = Field(None, min_length=4, max_length=20)
    status: Optional[str] = None
    arrival_date: Optional[date] = None
    tracking_status: Optional[str] = Field(None, max_length=120)
    free_days: Optional[int] = Field(None, ge=0, le=365)
    free_until: Optional[date] = None  # typed as a date: stored as days from the arrival
    clear_arrival: bool = False        # set arrival_date back to empty
    clear_free_days: bool = False      # back to the standard free days


class RefreshOut(BaseModel):
    found: bool
    added: int = 0
    updated: int = 0
    kept_manual: int = 0
    bl: Optional[dict] = None
    containers: list[ContainerOut] = []


def _shipment(db: Session, shipment_id: int, user: User) -> Shipment:
    s = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")
    allowed = get_user_allowed_ports(user)
    if allowed is not None and s.port not in allowed:
        raise HTTPException(status_code=403, detail="Not permitted to access this shipment")
    return s


def _out(c: ShipmentContainer, s: Shipment, today: Optional[date] = None) -> ContainerOut:
    o = ContainerOut.model_validate(c)
    today = today or date.today()
    # typed for this container, else the port's standard (Panipat 21, others 14)
    o.free_days = c.free_days if c.free_days is not None else alerts.icd_free_days(s.port)
    o.free_days_typed = c.free_days is not None
    if o.arrival_date is None and (s.port or "").upper() in alerts.SEA_PORTS:
        o.arrival_date = alerts.parse_inw(s.inw)  # sea port: free days from the INW
        o.arrival_from_inw = o.arrival_date is not None
    if o.arrival_date:
        o.day = (today - o.arrival_date).days + 1 if today >= o.arrival_date else None
        o.last_free_day = o.arrival_date + timedelta(days=o.free_days - 1)
        o.days_left = (o.last_free_day - today).days
    return o


def _list(db: Session, shipment_id: int) -> list[ShipmentContainer]:
    return (db.query(ShipmentContainer).filter(ShipmentContainer.shipment_id == shipment_id)
            .order_by(ShipmentContainer.container_no).all())


def _norm(no: str) -> str:
    return "".join(no.split()).upper()


@router.get("", response_model=list[ContainerOut])
def list_containers(shipment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _shipment(db, shipment_id, user)
    return [_out(c, s) for c in _list(db, shipment_id)]


@router.post("", response_model=ContainerOut, status_code=201)
def add_container(shipment_id: int, payload: ContainerIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    s = _shipment(db, shipment_id, user)
    no = _norm(payload.container_no)
    if not liners.container_ok(no):
        raise HTTPException(status_code=422, detail=f"{no} isn't a container number (4 letters + 7 digits, e.g. MRKU5032093)")
    if any(c.container_no == no for c in _list(db, shipment_id)):
        raise HTTPException(status_code=409, detail=f"{no} is already on this shipment")
    c = ShipmentContainer(shipment_id=shipment_id, container_no=no, status=payload.status,
                          arrival_date=payload.arrival_date, source="manual", is_manual=payload.arrival_date is not None)
    db.add(c)
    db.flush()
    record_change(db, "shipment_containers", c.id, "container_no", None, no, user.id)
    db.commit()
    return _out(c, s)


@router.patch("/{container_id}", response_model=ContainerOut)
def edit_container(shipment_id: int, container_id: int, payload: ContainerPatch, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    s = _shipment(db, shipment_id, user)
    c = db.query(ShipmentContainer).filter(ShipmentContainer.id == container_id,
                                           ShipmentContainer.shipment_id == shipment_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Container not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.pop("clear_arrival", False):
        changes["arrival_date"] = None
    if changes.pop("clear_free_days", False):
        changes["free_days"] = None
    free_until = changes.pop("free_until", None)
    if free_until is not None:
        arrival = changes.get("arrival_date", c.arrival_date) or _out(c, s).arrival_date
        if arrival is None:
            raise HTTPException(status_code=400, detail="Enter the arrival date first, or type the days free instead")
        if free_until < arrival:
            raise HTTPException(status_code=400, detail="Free until can't be before the arrival")
        changes["free_days"] = (free_until - arrival).days + 1
    if "tracking_status" in changes:
        changes["tracking_status"] = (changes["tracking_status"] or "").strip() or None
    if "container_no" in changes and changes["container_no"]:
        changes["container_no"] = _norm(changes["container_no"])
        if not liners.container_ok(changes["container_no"]):
            raise HTTPException(status_code=422, detail="Container number: 4 letters + 7 digits, e.g. MRKU5032093")
    for field, value in changes.items():
        old = getattr(c, field)
        if old == value:
            continue
        record_change(db, "shipment_containers", c.id, field, old, value, user.id)
        setattr(c, field, value)
        if field == "arrival_date":
            c.is_manual = True  # typed by hand: an ICEGATE refresh keeps it
    db.commit()
    return _out(c, s)


@router.delete("/{container_id}", status_code=204)
def remove_container(shipment_id: int, container_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _shipment(db, shipment_id, user)
    c = db.query(ShipmentContainer).filter(ShipmentContainer.id == container_id,
                                           ShipmentContainer.shipment_id == shipment_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Container not found")
    record_change(db, "shipment_containers", c.id, "deleted", c.container_no, None, user.id)
    soft_delete(db, c, user.id)
    db.commit()


def merge_sea(db: Session, shipment_id: int, found: list[dict], user_id: Optional[int]) -> int:
    """The sea IGM's container list — the primary source for which containers a shipment has (client):
    missing ones are added (type FCL / LCL filled where empty). Arrivals are left to the ICD / the INW.
    Returns how many were added."""
    have = {c.container_no: c for c in _list(db, shipment_id)}
    added = 0
    for x in found:
        m = re.search(r"[A-Z]{4}\d{7}", _norm(x.get("container") or ""))  # the cell may carry more than the number
        if not m:
            continue
        no = m.group()
        c = have.get(no)
        if c is None:
            c = ShipmentContainer(shipment_id=shipment_id, container_no=no, status=x.get("status"),
                                  source="icegate", is_manual=False)
            db.add(c)
            db.flush()
            record_change(db, "shipment_containers", c.id, "container_no", None, no, user_id)
            have[no] = c
            added += 1
        elif x.get("status") and not c.status:
            c.status = x["status"]
    return added


def merge_icd(db: Session, shipment_id: int, found: list[dict], user_id: Optional[int]) -> tuple[int, int, int]:
    """Put ICEGATE's containers onto the shipment: new ones added, arrival filled / updated —
    except where someone typed the arrival by hand. Returns (added, updated, kept_manual)."""
    have = {c.container_no: c for c in _list(db, shipment_id)}
    added = updated = kept = 0
    for x in found:
        no = _norm(x["container_no"])
        c = have.get(no)
        if c is None:
            c = ShipmentContainer(shipment_id=shipment_id, container_no=no, status=x.get("status"),
                                  arrival_date=x.get("arrival_date"), arrival_status=x.get("arrival_status"),
                                  source="icegate", is_manual=False)
            db.add(c)
            db.flush()
            record_change(db, "shipment_containers", c.id, "container_no", None, no, user_id)
            added += 1
            continue
        if x.get("status") and c.status != x["status"]:
            c.status = x["status"]
        if c.is_manual:
            kept += 1
            continue
        if x.get("arrival_date") != c.arrival_date and x.get("arrival_date") is not None:
            record_change(db, "shipment_containers", c.id, "arrival_date", c.arrival_date, x["arrival_date"], user_id)
            c.arrival_date = x["arrival_date"]
            c.arrival_status = x.get("arrival_status")
            c.source = "icegate"
            updated += 1
    return added, updated, kept


@router.post("/refresh-icd", response_model=RefreshOut)
def refresh_from_icegate(shipment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """On command: look the MBL up on ICEGATE's ICD BL status and merge the containers + arrivals."""
    s = _shipment(db, shipment_id, user)
    if not s.mbl:
        raise HTTPException(status_code=400, detail="This shipment has no MBL")
    try:
        data = icd.fetch(s.mbl)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="ICEGATE didn't answer — try again in a minute")
    if not data["found"]:
        return RefreshOut(found=False, containers=[_out(c, s) for c in _list(db, shipment_id)])
    added, updated, kept = merge_icd(db, shipment_id, data["containers"], user.id)
    db.commit()
    bl = data["bls"][0]
    return RefreshOut(found=True, added=added, updated=updated, kept_manual=kept,
                      bl={k: (v.isoformat() if isinstance(v, date) else v) for k, v in bl.items()},
                      containers=[_out(c, s) for c in _list(db, shipment_id)])

"""
Checks run on every shipment add / edit, so nonsense never gets saved.

Only the fields being changed are checked (old data that breaks a rule doesn't
block an unrelated edit). The tracker import writes the models directly and
skips these. Errors are plain English for a 422.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.enums import ShipmentStatus
from app.core.status_rules import proven_status
from app.models.port import Port
from app.models.shipment import Shipment

EARLIEST = date(2020, 1, 1)
DATE_LABELS = {
    "eta": "ETA", "be_dt": "BE date", "cleared_date": "Cleared date", "mbl_date": "MBL date",
    "hbl_date": "HBL date", "igm_date": "IGM date", "ooc_date": "OOC date",
}
NOT_FUTURE = {"be_dt", "cleared_date", "igm_date", "ooc_date", "mbl_date", "hbl_date"}
_ORDER = list(ShipmentStatus)


def _bad(msg: str) -> None:
    raise HTTPException(status_code=422, detail=msg)


def _today() -> date:
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()  # India time


def _blank(v: Any) -> bool:
    return v is None or str(v).strip() == ""


def mbl_key(v: Optional[str]) -> str:
    """One spelling per MBL for duplicate checks (HMM with or without HDMU match)."""
    k = re.sub(r"\s+", "", v or "").upper()
    return k[4:] if k.startswith("HDMUBHMA") else k


def parse_inw(v: str) -> Optional[date]:
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _number(v: str, label: str, *, whole: bool, unit: str = "") -> None:
    s = str(v).strip()
    if unit:
        s = re.sub(rf"\s*{unit}$", "", s, flags=re.I)
    pattern = r"^\d+$" if whole else r"^\d+(\.\d+)?$"
    if not re.match(pattern, s.replace(",", "")):
        _bad(f"{label} should be {'a whole number' if whole else 'a number'} (0 or more) — got “{v}”.")


def check_shipment(db: Session, shipment: Optional[Shipment], changes: dict) -> dict:
    """Validate + tidy `changes` (shipment=None when adding). Returns the tidied changes."""
    def now(f):  # value after this edit
        return changes[f] if f in changes else (getattr(shipment, f) if shipment else None)

    for f in ("job", "mbl", "hbl", "be_no", "igm", "port", "client", "container", "total_pkg", "gross_wt", "gw"):
        if isinstance(changes.get(f), str):
            changes[f] = changes[f].strip()
    if "port" in changes and changes["port"]:
        changes["port"] = changes["port"].upper()

    if "mbl" in changes and _blank(changes["mbl"]):
        _bad("The BL (MBL) no can't be empty.")
    if "client" in changes and _blank(changes["client"]) and shipment and not _blank(shipment.client):
        _bad("The client can't be emptied.")
    if "job" in changes and changes["job"] and not re.match(r"^[A-Za-z0-9/-]{1,20}$", changes["job"]):
        _bad(f"Job no “{changes['job']}” looks wrong — use digits (e.g. 192).")

    if not _blank(changes.get("be_no")) and not re.match(r"^\d{7}$", changes["be_no"]):
        _bad(f"BE no should be 7 digits — got “{changes['be_no']}”.")
    if not _blank(changes.get("igm")) and not re.match(r"^\d{1,7}$", changes["igm"]):
        _bad(f"IGM no should be digits only (up to 7) — got “{changes['igm']}”.")
    if ({"be_dt", "be_no"} & set(changes)) and now("be_dt") and _blank(now("be_no")):
        _bad("A BE date needs a BE no.")

    if changes.get("port"):
        if db.query(Port).count() and not db.query(Port).filter(Port.code == changes["port"]).first():
            _bad(f"Unknown port “{changes['port']}”. Pick one from the list (e.g. INMUN1).")

    for f, label, whole, unit in (("container", "Containers", True, ""), ("total_pkg", "Packages", True, ""),
                                  ("gross_wt", "Gross weight", False, "MTS"), ("gw", "Gross weight", False, "")):
        if not _blank(changes.get(f)):
            _number(changes[f], label, whole=whole, unit=unit)

    today = _today()
    latest = today + timedelta(days=366)
    for f, label in DATE_LABELS.items():
        d = changes.get(f)
        if d is None:
            continue
        if d < EARLIEST or d > latest:
            _bad(f"{label} {d:%d-%b-%Y} is out of range.")
        if f in NOT_FUTURE and d > today:
            _bad(f"{label} can't be in the future ({d:%d-%b-%Y}).")
    if not _blank(changes.get("inw")):
        d = parse_inw(changes["inw"])
        if d is None:
            _bad(f"Inward date “{changes['inw']}” isn't a date — use e.g. 05-Oct-2026.")
        if d < EARLIEST or d > today:
            _bad(f"Inward date {d:%d-%b-%Y} can't be in the future or before 2020.")
        changes["inw"] = d.strftime("%d-%b-%Y")
    if {"cleared_date", "eta"} & set(changes) and now("cleared_date") and now("eta") \
            and now("cleared_date") < now("eta"):
        _bad("Cleared date is before the ETA — fix the ETA first.")

    _check_duplicates(db, shipment, changes, now)

    if "status" in changes and changes["status"] is not None:
        st = ShipmentStatus(changes["status"])
        if st == ShipmentStatus.BILLED:
            _bad("Use the Bill button to mark a shipment billed.")
        if shipment and shipment.is_billed:
            _bad("This shipment is billed — cancel the bill first.")
        # the status can't run ahead of what the shipment's details prove
        probe = Shipment(**{c.key: getattr(shipment, c.key) for c in Shipment.__table__.columns} if shipment else {})
        for f, v in changes.items():
            if f != "status" and hasattr(probe, f):
                setattr(probe, f, v)
        proven = proven_status(probe)
        ok = _ORDER.index(st) <= _ORDER.index(proven) or (
            st == ShipmentStatus.UNDER_OOC and _ORDER.index(proven) >= _ORDER.index(ShipmentStatus.BE_FILED))
        if not ok:
            _bad(f"Status can't be “{st.value.replace('_', ' ')}” yet — the shipment's details only show "
                 f"“{proven.value.replace('_', ' ')}”. Fill in the BE no, duty, OOC, cleared date etc. first.")
    return changes


def _check_duplicates(db: Session, shipment: Optional[Shipment], changes: dict, now) -> None:
    others = db.query(Shipment)
    if shipment is not None:
        others = others.filter(Shipment.id != shipment.id)
    if {"mbl", "hbl"} & set(changes):
        key, hbl = mbl_key(now("mbl")), (now("hbl") or "").strip().upper()
        for o in others.filter(Shipment.mbl.ilike(f"%{key[-8:]}%")).all():
            if mbl_key(o.mbl) == key and (o.hbl or "").strip().upper() == hbl:
                _bad(f"BL {now('mbl')} is already on job {o.job or '(no job no)'} — {o.client or 'no client'}.")
    if changes.get("job"):
        # job numbers restart each year, so only open (not billed) shipments count
        o = others.filter(Shipment.job == changes["job"], Shipment.is_billed.is_(False)).first()
        if o:
            _bad(f"Job {changes['job']} is already used by BL {o.mbl}.")


def check_can_bill(shipment: Shipment) -> None:
    if shipment.cleared_date is None and shipment.status != ShipmentStatus.CLEARED:
        _bad("Can't bill yet — this shipment has no Cleared date.")

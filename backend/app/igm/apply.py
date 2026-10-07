"""
Write an ICEGATE IGM lookup (app/igm/icegate.py) onto a shipment, and cross-check it against the tracker —
like the client's sheet script: HBL, container count and weight mismatches become notes, never overwrites.
"""
import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.shipment_checks import eta_from_inward
from app.models.shipment import Shipment


def _date(v: Optional[str]) -> Optional[date]:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((v or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def _tonnes(gross_wt: Optional[str]) -> Optional[float]:
    """Tracker keeps '28.150 MTS'."""
    m = re.search(r"[\d.]+", gross_wt or "")
    return float(m.group()) if m else None


def plan(s: Shipment, data: dict) -> tuple[dict, list[str]]:
    """(field -> new value, notes). Only fields ICEGATE actually gave; the tracker's own
    Containers / Gross Wt / HBL are compared, not changed."""
    notes: list[str] = []
    if data.get("status") != "IGM Filed":
        return {}, ["IGM not filed yet on ICEGATE"]
    new = {
        "igm": data.get("igm_no"),
        "igm_date": _date(data.get("igm_date")),
        "inw": data.get("inw_date"),  # free text in the tracker's own format, e.g. 01-Aug-2026
        "line_no": data.get("line_no"),
        "voyage": data.get("voyage_no"),
        "mbl_date": _date(data.get("mbl_date")),
        "hbl_date": _date(data.get("hbl_date")),
        "total_pkg": data.get("total_package"),
        "pkg_code": data.get("package_code"),
        "cont": str(len(data["containers"])) if data.get("containers") else None,
    }
    unit = (data.get("unit_weight") or "").upper()
    if unit == "KGS":
        new["gw"] = data.get("gross_weight")
        tracker_t = _tonnes(s.gross_wt)
        try:
            icegate_t = float(data.get("gross_weight") or "") / 1000
            if tracker_t is not None and abs(tracker_t - icegate_t) > 0.001:
                notes.append(f"Weight differs: tracker {s.gross_wt}, IGM {data['gross_weight']} KGS")
        except ValueError:
            pass
    elif data.get("gross_weight"):
        notes.append(f"IGM weight not in KGS: {data['gross_weight']} {unit}")

    if s.hbl and data.get("hbl_no") and s.hbl.strip().upper() != data["hbl_no"].strip().upper():
        notes.append(f"HBL differs: tracker {s.hbl}, IGM {data['hbl_no']}")
    if data.get("containers") is not None and s.container:
        try:
            if int(s.container) != len(data["containers"]):
                notes.append(f"Containers differ: tracker {s.container}, IGM {len(data['containers'])}")
        except ValueError:
            pass
    if s.igm and new["igm"] and s.igm.strip() != new["igm"]:
        notes.append(f"IGM no. changed: was {s.igm}, ICEGATE {new['igm']}")

    eta = getattr(s, "eta", None)
    if eta_from_inward(eta, new["inw"]) != eta:
        new["eta"] = eta_from_inward(eta, new["inw"])  # inwarded before the ETA: the ETA was the inward date
    return {f: v for f, v in new.items() if v not in (None, "")}, notes


def apply(db: Session, s: Shipment, data: dict, user_id: Optional[int]) -> tuple[dict, list[str]]:
    """Write the lookup onto the shipment (audited). Returns (changed field -> (old, new), notes).
    Does not commit."""
    values, notes = plan(s, data)
    changed = {}
    for field, value in values.items():
        old = getattr(s, field)
        if old == value:
            continue
        record_change(db, "shipments", s.id, field, old, value, user_id)
        setattr(s, field, value)
        changed[field] = (old, value)
    return changed, notes

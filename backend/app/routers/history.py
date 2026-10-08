"""
Change history (client, 2026-09-30): the audit log, readable. Every change the ERP records — by a person or by
the ERP itself (ICEGATE, mails, invoices read) — with who, when, what, was → now.

- A shipment's history (its fields, containers and documents), for anyone who can open the shipment. A shipment
  field can be put back: the entry carries `undo` = {field: the old value}, which the page sends through the
  normal shipment edit (same checks, and the put-back is itself recorded). Only while nobody changed that field
  again since — otherwise undo the later change first.
- The whole log (admin): filter by who, what, dates and job / BL / text.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Integer, Numeric, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_user_allowed_ports, require_admin
from app.models.audit import AuditLogEntry
from app.models.container import ShipmentContainer
from app.models.document import ShipmentDocument
from app.models.shipment import Shipment
from app.models.user import User
from app.routers.containers import _shipment
from app.schemas.shipment import ShipmentUpdate

router = APIRouter(tags=["history"])

# what the page calls each table
KINDS = {"shipments": "Shipment", "shipment_containers": "Container", "shipment_documents": "Document",
         "proformas": "Proforma", "proforma_line_items": "Proforma line", "final_invoices": "Invoice",
         "payments": "Payment", "duty_challans": "Duty challan", "organizations": "Organisation",
         "app_settings": "Settings", "users": "User", "invoice_counters": "Invoice numbering",
         "charge_master_entries": "Rate rule", "licences": "Licence"}
EDITABLE = set(ShipmentUpdate.model_fields) - {"base", "custom_fields"}


def _labels(db: Session) -> dict[str, str]:
    from app.models.tracker_column import TrackerColumn

    return {c.key: c.label for c in db.query(TrackerColumn).all()}


_FIXED = {"missing_from_sheet": "Not in sheet",  # say what it is, not "missing"
          # the words the office uses (bagdu, v1.5.0): "Be dt" -> "BE date", "Igst amount" -> "IGST", …
          "be_dt": "BE date", "be_no": "BE No", "igst_amount": "IGST", "ooc_done": "OOC done", "remarks": "Notes",
          "duty_amount": "Duty", "bcd_amount": "BCD", "sws_amount": "SWS", "cleared_date": "Cleared date",
          "duty_paid": "Duty paid", "line_paid": "Shipping line paid", "cfs_inv_received": "CFS invoice received",
          "do": "DO", "ooc": "OOC", "eta_is_deadline": "ETA is a deadline", "inw": "Inward", "gross_wt": "Gross Wt"}
# short forms that stay in capitals when a field name is turned into words
_ACRONYMS = {"be", "bl", "mbl", "hbl", "igm", "igst", "ooc", "do", "cfs", "eta", "gst", "hs", "hss", "tds", "bcd", "sws",
             "pcv", "fpod", "pod", "icd", "inw", "gw", "pkg", "id", "coo", "iec", "gstin", "pan"}


def _words(field: str) -> str:
    words = [w.upper() if w in _ACRONYMS else w for w in field.split("_") if w]
    out = " ".join(words)
    return out[:1].upper() + out[1:]


def _label(field: str, labels: dict[str, str]) -> str:
    if field.startswith("custom:"):
        return labels.get(field[7:], field[7:])
    return _FIXED.get(field) or labels.get(field) or _words(field)


def _typed(field: str, raw: Optional[str], model=Shipment) -> tuple[bool, Any]:
    """The stored text back to the column's type — (ok, value). ok False = can't be put back safely."""
    col = model.__table__.columns.get(field)
    if col is None:
        return False, None
    if raw is None or raw == "None":
        return True, None
    t = col.type
    try:
        if isinstance(t, Boolean):
            return (raw in ("True", "False")), raw == "True"
        if isinstance(t, DateTime):
            return True, datetime.fromisoformat(raw).isoformat()
        if isinstance(t, Date):
            return True, date.fromisoformat(raw[:10]).isoformat()
        if isinstance(t, Numeric):
            return True, str(Decimal(raw))
        if isinstance(t, Integer):
            return True, int(raw)
        if isinstance(t, SAEnum):
            enum_cls = t.enum_class
            if enum_cls is not None:
                name = raw.split(".", 1)[1] if raw.startswith(enum_cls.__name__ + ".") else None
                for m in enum_cls:
                    if m.name == name or str(m.value) == raw:
                        return True, m.value
                return False, None
            return True, raw
    except (ValueError, InvalidOperation):
        return False, None
    return True, raw


# container fields History can put back (QA 2026-10-07), and how each is emptied through the container edit
BOX_UNDO = {"do_valid_until": "clear_do", "arrival_date": "clear_arrival", "free_days": "clear_free_days",
            "tracking_status": None}


def _box_undo(e: AuditLogEntry, c: Optional[ShipmentContainer]) -> Optional[dict]:
    if c is None or e.field_name not in BOX_UNDO or _current(c, e.field_name) != e.new_value:
        return None
    ok, value = _typed(e.field_name, e.old_value, ShipmentContainer)
    if not ok:
        return None
    if value is None:
        clear = BOX_UNDO[e.field_name]
        return {"container_id": c.id, **({clear: True} if clear else {e.field_name: ""})}
    return {"container_id": c.id, e.field_name: value}


def _current(s: Any, field: str) -> Optional[str]:
    """The field now, written the way record_change stores values (str)."""
    v = getattr(s, field, None)
    return str(v) if v is not None else None


def _row(e: AuditLogEntry, who: dict[int, str], labels: dict[str, str], ref: Optional[dict] = None) -> dict:
    return {"id": e.id, "at": e.changed_at, "who": who.get(e.changed_by_id) if e.changed_by_id else None,
            "automatic": e.changed_by_id is None, "table": e.table_name, "kind": KINDS.get(e.table_name, e.table_name),
            "record_id": e.record_id, "field": e.field_name, "label": _label(e.field_name, labels),
            "old": e.old_value, "new": e.new_value, **(ref or {})}


def _who(db: Session, entries) -> dict[int, str]:
    ids = {e.changed_by_id for e in entries if e.changed_by_id}
    return {u.id: u.full_name or u.email for u in db.query(User).filter(User.id.in_(ids))} if ids else {}


@router.get("/shipments/{shipment_id}/history")
def shipment_history(shipment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Newest first: the shipment's own fields, its containers and its documents."""
    s = _shipment(db, shipment_id, user)
    box_ids = [i for (i,) in db.query(ShipmentContainer.id).execution_options(include_deleted=True)
               .filter(ShipmentContainer.shipment_id == s.id)]
    doc = {d.id: d for d in db.query(ShipmentDocument).execution_options(include_deleted=True)
           .filter(ShipmentDocument.shipment_id == s.id)}
    box_rows = {c.id: c for c in db.query(ShipmentContainer).execution_options(include_deleted=True)
                .filter(ShipmentContainer.id.in_(box_ids))} if box_ids else {}
    boxes = {i: c.container_no for i, c in box_rows.items()}
    conds = [(AuditLogEntry.table_name == "shipments") & (AuditLogEntry.record_id == s.id)]
    if box_ids:
        conds.append((AuditLogEntry.table_name == "shipment_containers") & AuditLogEntry.record_id.in_(box_ids))
    if doc:
        conds.append((AuditLogEntry.table_name == "shipment_documents") & AuditLogEntry.record_id.in_(list(doc)))
    entries = (db.query(AuditLogEntry).filter(or_(*conds))
               .order_by(AuditLogEntry.changed_at.desc(), AuditLogEntry.id.desc()).limit(1000).all())
    who, labels = _who(db, entries), _labels(db)
    latest: dict[str, int] = {}  # field -> newest entry id (only the newest change of a field can be put back)
    box_latest: dict[tuple[int, str], int] = {}
    for e in entries:
        if e.table_name == "shipments":
            latest.setdefault(e.field_name, e.id)
        elif e.table_name == "shipment_containers":
            box_latest.setdefault((e.record_id, e.field_name), e.id)
    out = []
    for e in entries:
        ref = {}
        if e.table_name == "shipment_containers":
            ref["about"] = boxes.get(e.record_id)
        elif e.table_name == "shipment_documents":
            d = doc.get(e.record_id)
            ref["about"] = (d.original_filename or d.document_type.value) if d else None
        r = _row(e, who, labels, ref)
        r["undo"] = None
        if e.table_name == "shipments" and e.field_name in EDITABLE and latest.get(e.field_name) == e.id \
                and _current(s, e.field_name) == e.new_value:
            ok, value = _typed(e.field_name, e.old_value)
            if ok:
                r["undo"] = {e.field_name: value}
        elif e.table_name == "shipment_containers" and box_latest.get((e.record_id, e.field_name)) == e.id:
            c = box_rows.get(e.record_id)
            r["undo"] = _box_undo(e, c if c is not None and c.deleted_at is None else None)
        out.append(r)
    return out


@router.get("/history")
def all_history(who: Optional[str] = Query(None, description="user id, or 'auto' for the ERP's own changes"),
                kind: Optional[str] = Query(None, description="table name, e.g. shipments"),
                date_from: Optional[date] = None, date_to: Optional[date] = None,
                q: Optional[str] = Query(None, description="job, BL, BE, field or value"),
                limit: int = Query(300, le=5000),
                db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """The whole change log, newest first (admin)."""
    query = db.query(AuditLogEntry)
    if who == "auto":
        query = query.filter(AuditLogEntry.changed_by_id.is_(None))
    elif who:
        query = query.filter(AuditLogEntry.changed_by_id == int(who))
    if kind:
        query = query.filter(AuditLogEntry.table_name == kind)
    ist = timezone(timedelta(hours=5, minutes=30))
    if date_from:
        query = query.filter(AuditLogEntry.changed_at >= _when(db, datetime.combine(date_from, datetime.min.time(), ist)))
    if date_to:
        query = query.filter(AuditLogEntry.changed_at < _when(db, datetime.combine(date_to + timedelta(days=1), datetime.min.time(), ist)))
    if q and q.strip():
        t = f"%{q.strip()}%"
        ship_ids = [i for (i,) in db.query(Shipment.id).execution_options(include_deleted=True).filter(
            or_(Shipment.job.ilike(t), Shipment.mbl.ilike(t), Shipment.hbl.ilike(t), Shipment.be_no.ilike(t)))]
        box_ids = [i for (i,) in db.query(ShipmentContainer.id).execution_options(include_deleted=True).filter(
            or_(ShipmentContainer.shipment_id.in_(ship_ids or [-1]), ShipmentContainer.container_no.ilike(t)))]
        query = query.filter(or_(
            AuditLogEntry.field_name.ilike(t), AuditLogEntry.old_value.ilike(t), AuditLogEntry.new_value.ilike(t),
            (AuditLogEntry.table_name == "shipments") & AuditLogEntry.record_id.in_(ship_ids or [-1]),
            (AuditLogEntry.table_name == "shipment_containers") & AuditLogEntry.record_id.in_(box_ids or [-1])))
    entries = query.order_by(AuditLogEntry.changed_at.desc(), AuditLogEntry.id.desc()).limit(limit).all()
    who_names, labels = _who(db, entries), _labels(db)
    ships = {s.id: s for s in db.query(Shipment).execution_options(include_deleted=True).filter(
        Shipment.id.in_({e.record_id for e in entries if e.table_name == "shipments"} or {-1}))}
    allowed = get_user_allowed_ports(admin)
    out = []
    for e in entries:
        ref = {}
        s = ships.get(e.record_id) if e.table_name == "shipments" else None
        if s is not None:
            if allowed is not None and s.port not in allowed:
                continue
            ref = {"shipment_id": s.id, "job": s.job, "mbl": s.mbl, "be_no": s.be_no}
        out.append(_row(e, who_names, labels, ref))
    return out


@router.get("/history/filters")
def history_filters(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Who can be picked, and which kinds of record."""
    users = [{"id": u.id, "name": u.full_name or u.email} for u in db.query(User).order_by(User.full_name)]
    kinds = [{"kind": t, "label": KINDS.get(t, t)} for (t,) in db.query(AuditLogEntry.table_name).distinct()]
    return {"users": users, "kinds": sorted(kinds, key=lambda k: k["label"])}


def _when(db: Session, dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None) if db.bind.dialect.name == "sqlite" else dt

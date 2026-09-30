from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.locking import locked_shipment_or_404
from app.core.deps import get_current_user, require_admin, require_billing_access, get_user_allowed_ports
from app.core.enums import ShipmentStatus, UserRole
from app.invoice.autofill import refresh_draft_proformas
from app import alerts
from app.models.audit import AuditLogEntry
from app.models.container import ShipmentContainer
from app.models.document import ShipmentDocument
from app.routers.documents import COMBINED_DOCUMENTS
from app.models.settings import get_setting
from app.models.shipment import Shipment
from app.models.soft_delete import soft_delete
from app.models.tracker_column import TrackerColumn
from app.models.user import User
from app.schemas.shipment import ClientRename, ClientRenameOut, ValueRename, ShipmentCreate, ShipmentUpdate, ShipmentOut
from app.core.audit import record_change
from app.core.status_rules import EVIDENCE_FIELDS, proven_status, status_after_evidence_change

# shipment fields that draft proformas are built from
PROFORMA_INPUTS = {"cfs_paid_by_us", "cfs_billed_as", "line_paid_by_us", "line_cost_inclusion", "duty_amount", "igst_amount",
                   "assessable_value", "port", "be_no", "cfs_amount_before_tax", "cfs_gst_amount",
                   "under_examination", "container"}

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=list[ShipmentOut])
def list_shipments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    port: Optional[str] = Query(None, description="Filter to a single port"),
    status_filter: Optional[ShipmentStatus] = Query(None, alias="status"),
    is_stuck: Optional[bool] = Query(None),
    include_archived: bool = Query(False, description="Include billed/archived shipments"),
    search: Optional[str] = Query(None, description="Free-text match on job/mbl/hbl/be_no/client/consignee"),
):
    """
    Core grid-view endpoint (spec §2.5). Port scoping (spec §2.4) is applied
    automatically based on the requesting user's `port_access` rows — a user
    with no port restriction sees everything, a scoped user only sees their
    assigned ports regardless of what `port` filter they pass.
    """
    q = db.query(Shipment)

    if not include_archived:
        q = q.filter(Shipment.is_archived.is_(False))

    allowed_ports = get_user_allowed_ports(current_user)
    if allowed_ports is not None:
        q = q.filter(Shipment.port.in_(allowed_ports))
        if port and port not in allowed_ports:
            raise HTTPException(status_code=403, detail="Not permitted to view this port")

    if port:
        q = q.filter(Shipment.port == port)
    if status_filter:
        q = q.filter(Shipment.status == status_filter)
    if is_stuck is not None:
        q = q.filter(Shipment.is_stuck == is_stuck)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Shipment.job.ilike(like))
            | (Shipment.mbl.ilike(like))
            | (Shipment.hbl.ilike(like))
            | (Shipment.be_no.ilike(like))
            | (Shipment.client.ilike(like))
            | (Shipment.consignee.ilike(like))
        )

    return q.order_by(Shipment.eta.asc().nullslast()).all()


def _containers(s: Shipment) -> int:
    """The tracker's Cntr column is text; blank or unreadable counts as 0."""
    try:
        return max(0, int(str(s.container or "").strip().split()[0]))
    except (ValueError, IndexError):
        return 0


def _tonnes(s: Shipment) -> float:
    """Gross Wt is text like '124.270 MTS' (tonnes); 'KGS' is converted; anything else counts as 0."""
    import re

    text = str(s.gross_wt or "").replace(",", "").upper()
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return 0.0
    n = float(m.group())
    return n / 1000 if "KG" in text else n


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def container_metrics(shipments: list[Shipment], today: date) -> dict:
    """Dashboard (client, 2026-09-29): containers and gross weight — what matters, not the
    number of shipments — per month by ETA and by Cleared Date, each split by port; the
    last 12 months up to 2 months ahead."""
    first = date(today.year - (1 if today.month <= 11 else 0), (today.month - 11 - 1) % 12 + 1, 1)
    last_y, last_m = (today.year + (today.month + 1) // 12, (today.month + 1) % 12 + 1)
    last = date(last_y, last_m, 1)

    def series(get_date) -> list[dict]:
        months: dict[str, dict] = {}
        for s in shipments:
            d = get_date(s)
            if d is None or not (first <= date(d.year, d.month, 1) <= last):
                continue
            m = months.setdefault(_month(d), {"month": _month(d), "containers": 0, "tonnes": 0.0, "by_port": {}})
            n, t = _containers(s), _tonnes(s)
            m["containers"] += n
            m["tonnes"] += t
            port = m["by_port"].setdefault(s.port or "Unassigned", {"containers": 0, "tonnes": 0.0})
            port["containers"] += n
            port["tonnes"] += t
        out = [months[k] for k in sorted(months)]
        for m in out:  # tonnes to 3 decimals, like the tracker
            m["tonnes"] = round(m["tonnes"], 3)
            for p in m["by_port"].values():
                p["tonnes"] = round(p["tonnes"], 3)
        return out

    prev = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    return {
        "containers_by_eta_month": series(lambda s: s.eta),
        "containers_cleared_by_month": series(lambda s: s.cleared_date if s.is_fully_cleared else None),
        "this_month": _month(today),
        "last_month": _month(prev),
    }


@router.get("/summary/dashboard")
def get_dashboard_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Backs the Tracker Dashboard view. "Live" = ongoing: not archived and no
    Cleared Date yet (a cleared shipment isn't tracked live any more — it
    moves to the Cleared section). Same port-scoping as the grid endpoint.
    """
    q = db.query(Shipment)
    allowed_ports = get_user_allowed_ports(current_user)
    if allowed_ports is not None:
        q = q.filter(Shipment.port.in_(allowed_ports))
    everything = q.all()
    live = [s for s in everything if not s.is_fully_cleared]
    today = date.today()
    cleared_this_month = [
        s for s in everything
        if s.is_fully_cleared and (s.cleared_date.year, s.cleared_date.month) == (today.year, today.month)
    ]

    by_status: dict[str, int] = {s.value: 0 for s in ShipmentStatus}
    by_port: dict[str, int] = {}
    stuck_count = 0
    for s in live:
        by_status[s.status.value] = by_status.get(s.status.value, 0) + 1
        if s.is_stuck:
            stuck_count += 1
        port_key = s.port or "Unassigned"
        by_port[port_key] = by_port.get(port_key, 0) + 1

    upcoming = sorted((s for s in live if s.eta and s.eta >= today), key=lambda s: s.eta)[:5]
    containers = container_metrics(everything, today)

    return {
        "total_live": len(live),
        "stuck_count": stuck_count,
        "cleared_this_month": len(cleared_this_month),
        # Cleared Date entered but a check (Duty / CFS Inv / Line / OOC / DO) still missing
        "clearance_exceptions": sum(1 for s in live if s.cleared_date is not None),
        "cleared_this_month_unbilled": sum(1 for s in cleared_this_month if not s.is_billed),
        "by_status": by_status,
        "by_port": by_port,
        **containers,
        "live_containers": sum(_containers(s) for s in live),
        "live_tonnes": round(sum(_tonnes(s) for s in live), 3),
        "upcoming_etas": [
            {"id": s.id, "job": s.job, "mbl": s.mbl, "be_no": s.be_no, "consignee": s.consignee, "eta": s.eta, "port": s.port}
            for s in upcoming
        ],
    }


@router.get("/alerts")
def get_alerts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Dashboard "Needs attention": "d" deadlines, free days at the POD, documents missing
    before the BE is filed (app/alerts.py). Live shipments only, same port scoping as the grid."""
    q = db.query(Shipment).filter(Shipment.is_archived.is_(False), Shipment.cleared_date.is_(None))
    allowed_ports = get_user_allowed_ports(current_user)
    if allowed_ports is not None:
        q = q.filter(Shipment.port.in_(allowed_ports))
    live = q.all()
    uploaded: dict[int, set] = {s.id: set() for s in live}
    if live:
        for shipment_id, doc_type in db.query(ShipmentDocument.shipment_id, ShipmentDocument.document_type).filter(
            ShipmentDocument.shipment_id.in_(list(uploaded))
        ):
            uploaded[shipment_id].add(doc_type)
            uploaded[shipment_id].update(COMBINED_DOCUMENTS.get(doc_type, ()))
    boxes: dict[int, list] = {s.id: [] for s in live}
    if live:
        for c in db.query(ShipmentContainer).filter(ShipmentContainer.shipment_id.in_(list(boxes))):
            boxes[c.shipment_id].append((c.container_no, c.arrival_date, c.free_days))
    today = date.today()
    found = []
    for s in live:
        required = [(rd.document_type, rd.optional) for rd in (s.hs_code.required_documents if s.hs_code else [])]
        for alert in (
            alerts.deadline_alert(s, today),
            alerts.free_days_alert(s, today),
            alerts.fpod_alert(s, boxes[s.id], today),
            alerts.documents_alert(s, required, uploaded[s.id], today),
            alerts.lookup_alert(s, today),
        ):
            if alert:
                found.append(alert)
    # ICEGATE mails still open: B/E Negative Ack, B/E Query, failed filing
    from app.models.icegate_mail import IcegateMail

    by_id = {s.id: s for s in live}
    if by_id:
        for m in (db.query(IcegateMail).filter(IcegateMail.attention.is_(True), IcegateMail.resolved_at.is_(None),
                                               IcegateMail.shipment_id.in_(list(by_id)))
                  .order_by(IcegateMail.received_at)):
            found.append({**alerts._base(by_id[m.shipment_id]), "kind": "icegate", "severity": "urgent", "days_left": 0,
                          "due": None, "mail_id": m.id, "text": f"{m.label}: {m.summary}"})
    return alerts.sort_alerts(found)


@router.post("/rename-value", response_model=ClientRenameOut)
def rename_value(payload: ValueRename, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Rename a client or consignee on every shipment that has it (incl.
    archived), each row audit-logged. Matching ignores surrounding spaces;
    renaming onto an existing name merges the two. Port-scoped users only
    rename shipments they can see."""
    field, old, new = payload.field, payload.old_name.strip(), payload.new_name.strip()
    if not new:
        raise HTTPException(status_code=400, detail="New name can't be empty")
    column = getattr(Shipment, field)
    q = db.query(Shipment).filter(column.isnot(None))
    allowed_ports = get_user_allowed_ports(current_user)
    if allowed_ports is not None:
        q = q.filter(Shipment.port.in_(allowed_ports))
    q = q.order_by(Shipment.id).with_for_update().populate_existing()  # lock in id order
    rows = [s for s in q if getattr(s, field).strip() == old]
    for s in rows:
        if getattr(s, field) != new:
            record_change(db, "shipments", s.id, field, getattr(s, field), new, current_user.id)
            setattr(s, field, new)
            if field == "consignee":
                _rederive_hss(db, s, current_user.id)
    db.commit()
    return ClientRenameOut(updated=len(rows))


@router.post("/rename-client", response_model=ClientRenameOut)
def rename_client(payload: ClientRename, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return rename_value(ValueRename(field="client", **payload.model_dump()), db, current_user)


@router.get("/{shipment_id}", response_model=ShipmentOut)
def get_shipment(shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    shipment = _get_shipment_or_404(db, shipment_id)
    _check_port_access(shipment, current_user)
    return _with_final_duty(db, shipment)


@router.post("", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
def create_shipment(payload: ShipmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = payload.model_dump()
    explicit_hss = data.pop("is_hss")
    shipment = Shipment(**data, created_by_id=current_user.id)
    if explicit_hss is None:
        if not (shipment.hss_seller or shipment.hss_buyer):
            shipment.apply_hss_from_consignee()
    else:
        shipment.is_hss = explicit_hss
    shipment.status = shipment.status or ShipmentStatus.TO_BE_FILED
    shipment.status = proven_status(shipment)
    db.add(shipment)
    db.commit()
    db.refresh(shipment)
    return shipment


@router.patch("/{shipment_id}", response_model=ShipmentOut)
def update_shipment(
    shipment_id: int,
    payload: ShipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shipment = _get_shipment_or_404(db, shipment_id)
    _check_port_access(shipment, current_user)
    shipment = locked_shipment_or_404(db, shipment_id)  # the rest is one short locked transaction

    changes = payload.model_dump(exclude_unset=True)
    base = changes.pop("base", None)
    if base:
        conflicts = _conflicts(db, shipment, changes, base)
        if conflicts:
            raise HTTPException(status_code=409, detail={
                "message": "Someone else changed this since you loaded it.",
                "conflicts": conflicts, "version": shipment.version,
                "shipment": ShipmentOut.model_validate(shipment).model_dump(mode="json")})
    custom = changes.pop("custom_fields", None)
    if changes.get("cfs_paid_by_us") and not shipment.cfs_paid_by_us and "tds_on_cfs" not in changes:
        changes["tds_on_cfs"] = True  # we normally cut 2% TDS when we pay the CFS
    if changes.get("cfs_tds_rate") is not None:
        rate = Decimal(changes["cfs_tds_rate"])
        if rate == 2:
            changes["cfs_tds_rate"] = None  # the usual rate: keep it empty
        elif not get_setting(db, "tds_rate_editable"):
            raise HTTPException(status_code=422, detail="TDS on CFS is fixed at 2%. The admin can allow other rates in Settings.")
        elif not (0 < rate <= 20):
            raise HTTPException(status_code=422, detail="TDS rate should be between 0% and 20%")
    if custom:
        _apply_custom_fields(db, shipment, custom, current_user.id)
    evidence_changed = False
    for field, new_value in changes.items():
        old_value = getattr(shipment, field)
        if old_value != new_value:
            record_change(db, "shipments", shipment.id, field, old_value, new_value, current_user.id)
            setattr(shipment, field, new_value)
            evidence_changed |= field in EVIDENCE_FIELDS

    # HSS follows the consignee name ("SELLER - BUYER") unless set in this edit
    if "consignee" in changes and not {"is_hss", "hss_seller", "hss_buyer"} & set(changes):
        _rederive_hss(db, shipment, current_user.id)

    # Status follows the evidence (IGM no -> IGM Filed, etc.) unless the user
    # set the status themselves in this same edit.
    if evidence_changed and "status" not in changes:
        new_status = status_after_evidence_change(shipment)
        if new_status is not None:
            record_change(db, "shipments", shipment.id, "status", shipment.status, new_status, current_user.id)
            shipment.status = new_status

    if set(changes) & PROFORMA_INPUTS:
        refresh_draft_proformas(db, shipment)  # e.g. paid-by-us switches, duty figures, port
    db.commit()
    db.refresh(shipment)
    return _with_final_duty(db, shipment)


@router.delete("/{shipment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shipment(shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Admin only. Soft delete: the shipment (with its documents, proformas and
    invoices) disappears everywhere but stays in the database; the admin can restore
    it from Recently deleted."""
    shipment = locked_shipment_or_404(db, shipment_id)
    record_change(db, "shipments", shipment.id, "deleted", shipment.mbl, None, current_user.id)
    soft_delete(db, shipment, current_user.id)
    db.commit()


@router.post("/{shipment_id}/bill", response_model=ShipmentOut)
def mark_shipment_billed(shipment_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(require_billing_access)):
    """
    Spec §5.5: mark a shipment Billed (the "Billed?" tick in the tracker).
    Final-bill document generation is out of v1 scope (LiveImpex decision
    pending). Where the shipment shows in the tracker is still decided by its
    Cleared Date, so billing never makes a shipment disappear. Audit-logged.
    """
    from datetime import datetime, timezone

    shipment = _get_shipment_or_404(db, shipment_id)
    _check_port_access(shipment, current_user)
    shipment = locked_shipment_or_404(db, shipment_id)
    if shipment.is_billed:
        return shipment
    changes = {"is_billed": True, "is_archived": True, "billed_at": datetime.now(timezone.utc),
               "status": ShipmentStatus.BILLED}
    for field, value in changes.items():
        record_change(db, "shipments", shipment.id, field, getattr(shipment, field), value, current_user.id)
        setattr(shipment, field, value)
    db.commit()
    db.refresh(shipment)
    return _with_final_duty(db, shipment)


@router.post("/{shipment_id}/unbill", response_model=ShipmentOut)
def unbill_shipment(shipment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Spec §5.5: reversible — pull a billed shipment back if the bill is
    cancelled. Admin-only. The status goes back to what it was just before it
    was billed (from the change history)."""
    shipment = locked_shipment_or_404(db, shipment_id)
    if not shipment.is_billed:
        return shipment
    previous = (
        db.query(AuditLogEntry)
        .filter(AuditLogEntry.table_name == "shipments", AuditLogEntry.record_id == shipment.id,
                AuditLogEntry.field_name == "status", AuditLogEntry.new_value == str(ShipmentStatus.BILLED))
        .order_by(AuditLogEntry.id.desc())
        .first()
    )
    restored = _status_from_audit(previous.old_value if previous else None) or (
        ShipmentStatus.CLEARED if shipment.cleared_date else ShipmentStatus.OOC_DONE if shipment.ooc
        else ShipmentStatus.TO_BE_FILED)
    changes = {"is_billed": False, "is_archived": False, "billed_at": None,
               "status": restored if shipment.status == ShipmentStatus.BILLED else shipment.status}
    for field, value in changes.items():
        if getattr(shipment, field) != value:
            record_change(db, "shipments", shipment.id, field, getattr(shipment, field), value, current_user.id)
            setattr(shipment, field, value)
    db.commit()
    db.refresh(shipment)
    return _with_final_duty(db, shipment)


def _status_from_audit(raw: Optional[str]) -> Optional[ShipmentStatus]:
    for st in ShipmentStatus:
        if raw in (str(st), st.value, st.name):
            return st
    return None


def _rederive_hss(db: Session, shipment: Shipment, user_id: int) -> None:
    before = (shipment.is_hss, shipment.hss_seller, shipment.hss_buyer)
    shipment.apply_hss_from_consignee()
    for field, old in zip(("is_hss", "hss_seller", "hss_buyer"), before):
        if getattr(shipment, field) != old:
            record_change(db, "shipments", shipment.id, field, old, getattr(shipment, field), user_id)


def _apply_custom_fields(db: Session, shipment: Shipment, values: dict, user_id: int) -> None:
    """Merge values for user-created columns; each changed key is audit-logged."""
    allowed = {c.key for c in db.query(TrackerColumn).filter(TrackerColumn.is_custom.is_(True))}
    unknown = set(values) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown column(s): {', '.join(sorted(unknown))}")
    merged = dict(shipment.custom_fields or {})
    for key, new_value in values.items():
        if isinstance(new_value, str):
            new_value = new_value.strip() or None
        old_value = merged.get(key)
        if old_value != new_value:
            record_change(db, "shipments", shipment.id, f"custom:{key}", old_value, new_value, user_id)
            if new_value is None:
                merged.pop(key, None)
            else:
                merged[key] = new_value
    shipment.custom_fields = merged  # reassign so SQLAlchemy sees the JSON change


def _same(a: Any, b: Any) -> bool:
    """Equal as the user sees them: blank == None, 12.5 == "12.50"."""
    a = None if a in (None, "") else a
    b = None if b in (None, "") else b
    if a == b:
        return True
    if a is None or b is None or isinstance(a, bool) or isinstance(b, bool):
        return False
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return str(a).strip() == str(b).strip()


def _conflicts(db: Session, shipment: Shipment, changes: dict, base: dict) -> list[dict]:
    """Fields this edit changes whose value moved since the user loaded it (and that
    the user isn't setting to the value already there)."""
    current = ShipmentOut.model_validate(shipment).model_dump(mode="json")
    checks = [(f, f, current.get(f), v, base[f]) for f, v in changes.items()
              if f in base and f != "custom_fields"]
    cur_custom, base_custom = current.get("custom_fields") or {}, base.get("custom_fields") or {}
    checks += [(f"custom:{k}", k, cur_custom.get(k), v, base_custom[k])
               for k, v in (changes.get("custom_fields") or {}).items() if k in base_custom]
    out = []
    for audit_field, field, now, yours, seen in checks:
        if _same(now, seen) or _same(now, yours):
            continue
        last = (db.query(AuditLogEntry)
                .filter(AuditLogEntry.table_name == "shipments", AuditLogEntry.record_id == shipment.id,
                        AuditLogEntry.field_name == audit_field)
                .order_by(AuditLogEntry.id.desc()).first())
        who = db.get(User, last.changed_by_id) if last and last.changed_by_id else None
        out.append({"field": field, "current": now, "yours": yours, "base": seen,
                    "changed_by": who.full_name if who else None,
                    "changed_at": last.changed_at.isoformat() if last and last.changed_at else None})
    return out


def _with_final_duty(db: Session, shipment: Shipment) -> Shipment:
    """Customs duty as actually payable — BE duty + interest from the duty challan, or the OOC copy's
    total (the final amount paid) — for the Overview's Customs duty block (client, 2026-09-30)."""
    from app.invoice.build import customs_duty, latest_challan  # avoid an import cycle at load time
    duty = customs_duty(shipment, latest_challan(db, shipment.be_no, shipment.be_dt)) if shipment.be_no else None
    shipment.final_duty = None if duty is None else {
        "total": str(duty["total"]), "interest": str(duty["interest"]), "source": duty["source"]}
    return shipment


def _get_shipment_or_404(db: Session, shipment_id: int) -> Shipment:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


def _check_port_access(shipment: Shipment, user: User) -> None:
    allowed_ports = get_user_allowed_ports(user)
    if allowed_ports is not None and shipment.port not in allowed_ports:
        raise HTTPException(status_code=403, detail="Not permitted to access this shipment's port")

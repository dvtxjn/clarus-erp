"""Recently deleted: the admin sees every soft-deleted shipment, document, proforma
and final invoice, and can restore it (launch Phase 1)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import storage
from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin
from app.extraction.cfs_totals import INVOICE_DOC_TYPES, recompute_invoice_totals
from app.invoice.autofill import refresh_draft_proformas
from app.models.document import ShipmentDocument
from app.models.final_invoice import FinalInvoice
from app.models.payment import Payment
from app.models.proforma import Proforma
from app.models.shipment import Shipment
from app.models.soft_delete import restore
from app.models.user import User

router = APIRouter(prefix="/deleted", tags=["recently deleted"], dependencies=[Depends(require_admin)])

Kind = Literal["shipment", "document", "proforma", "final_invoice", "payment"]
MODELS = {"shipment": Shipment, "document": ShipmentDocument, "proforma": Proforma, "final_invoice": FinalInvoice,
          "payment": Payment}
TABLES = {"shipment": "shipments", "document": "shipment_documents", "proforma": "proformas",
          "final_invoice": "final_invoices", "payment": "payments"}


def _all(db: Session, model):
    return db.query(model).execution_options(include_deleted=True)


def _label(kind: str, obj) -> str:
    if kind == "shipment":
        return f"Shipment {obj.job or ''} {obj.mbl or ''}".replace("  ", " ").strip()
    if kind == "document":
        return obj.generated_filename or obj.original_filename or obj.document_type.value
    if kind == "proforma":
        return f"Proforma v{obj.version_number}" + (f" · {obj.name}" if obj.name else "")
    if kind == "payment":
        return f"Payment ₹{obj.amount:,.2f} from {obj.party} ({obj.received_on:%d %b %Y})"
    return f"{'Tax' if obj.kind == 'tax' else 'Reimbursement'} invoice (draft)"


@router.get("")
def list_deleted(db: Session = Depends(get_db)):
    users = {u.id: u.full_name for u in db.query(User)}
    ships = {s.id: s for s in _all(db, Shipment)}
    out = []
    for kind, model in MODELS.items():
        for obj in _all(db, model).filter(model.deleted_at.isnot(None)):
            ship = obj if kind == "shipment" else ships.get(getattr(obj, "shipment_id", None))
            out.append({
                "kind": kind, "id": obj.id, "label": _label(kind, obj),
                "shipment_id": ship.id if ship else None,
                "shipment": f"{ship.job or ''} · {ship.mbl or ''} · {ship.consignee or ''}".strip(" ·") if ship else None,
                "shipment_deleted": bool(ship and ship.is_deleted and kind != "shipment"),
                "deleted_at": obj.deleted_at, "deleted_by": users.get(obj.deleted_by_id),
            })
    return sorted(out, key=lambda r: r["deleted_at"], reverse=True)


@router.post("/{kind}/{item_id}/restore")
def restore_item(kind: Kind, item_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    model = MODELS[kind]
    obj = _all(db, model).filter(model.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    if not obj.is_deleted:
        raise HTTPException(status_code=400, detail="This isn't deleted")
    if kind not in ("shipment", "payment"):
        ship = _all(db, Shipment).filter(Shipment.id == obj.shipment_id).first()
        if ship and ship.is_deleted:
            raise HTTPException(status_code=400, detail="Its shipment is deleted — restore the shipment first")
    if kind == "final_invoice":
        clash = db.query(FinalInvoice).filter(FinalInvoice.proforma_id == obj.proforma_id,
                                              FinalInvoice.kind == obj.kind,
                                              FinalInvoice.status.in_(("draft", "issued"))).first()
        if clash:
            raise HTTPException(status_code=400, detail=f"This proforma already has a {clash.status} "
                                                        f"{obj.kind} invoice — delete or cancel that one first")
    restore(db, obj)
    record_change(db, TABLES[kind], obj.id, "restored", None, _label(kind, obj), admin.id)
    if kind == "document":
        storage.mark_removed(obj, False)  # Drive name back without "[removed] "
        ship = db.get(Shipment, obj.shipment_id)
        if obj.document_type in INVOICE_DOC_TYPES:
            recompute_invoice_totals(db, ship, admin.id)
        refresh_draft_proformas(db, ship)
    db.commit()
    return {"kind": kind, "id": item_id, "restored": True}

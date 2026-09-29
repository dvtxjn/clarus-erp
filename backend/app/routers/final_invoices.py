"""Final invoices (tax / reimbursement): made from a proforma, edited by hand while
draft (every change audit-logged — this is what goes to the authorities), then issued
(numbered + locked). See app/invoice/final.py."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.invoice.final import TAX_TYPES, compute, create_from_proforma, issue
from app.invoice.final_pdf import render_final_pdf
from app.models.final_invoice import FinalInvoice, InvoiceCounter
from app.models.proforma import Proforma
from app.models.soft_delete import soft_delete
from app.models.user import User

# Every route here is invoicing: admin-only, including reads (see require_billing_access)
router = APIRouter(tags=["final invoices"], dependencies=[Depends(require_billing_access)])


class FinalLine(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    sub_description: Optional[str] = Field(default=None, max_length=200)
    sac: Optional[str] = Field(default=None, max_length=20)
    tax_type: Literal["T", "P", "E", "R", "N"] = "T"
    non_gst_value: Decimal = Field(default=Decimal("0"), ge=0)
    taxable_value: Decimal = Field(default=Decimal("0"), ge=0)
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=28)


class FinalInvoiceUpdate(BaseModel):
    """Manual overrides. Draft: anything. Issued: only irn / ack_no / ack_date."""
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    customer: Optional[dict[str, Any]] = None
    header: Optional[dict[str, Any]] = None
    lines: Optional[list[FinalLine]] = None
    advance_received: Optional[Decimal] = Field(default=None, ge=0)
    remarks: Optional[str] = Field(default=None, max_length=500)
    irn: Optional[str] = Field(default=None, max_length=100)
    ack_no: Optional[str] = Field(default=None, max_length=50)
    ack_date: Optional[str] = Field(default=None, max_length=30)


class CancelIn(BaseModel):
    reason: Optional[str] = None


class CounterIn(BaseModel):
    fy: str = Field(pattern=r"^\d{2}-\d{2}$")
    next_seq: int = Field(ge=1)


def _get(db: Session, invoice_id: int) -> FinalInvoice:
    inv = db.get(FinalInvoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.post("/proformas/{proforma_id}/final-invoices", status_code=201)
def create_final_invoices(proforma_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_billing_access)):
    """Draft Tax Invoice (Billed by Clarus lines) + Reimbursement Invoice (charges paid
    by us). Existing DRAFTS from this proforma are replaced; issued ones are kept."""
    proforma = db.get(Proforma, proforma_id)
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma not found")
    issued = db.query(FinalInvoice).filter(FinalInvoice.proforma_id == proforma_id,
                                           FinalInvoice.status == "issued").count()
    if issued:
        raise HTTPException(status_code=400, detail="Final invoices from this proforma are already issued — "
                                                    "cancel them first, or make a new proforma version.")
    for old in db.query(FinalInvoice).filter(FinalInvoice.proforma_id == proforma_id, FinalInvoice.status == "draft").all():
        record_change(db, "final_invoices", old.id, "deleted", old.kind, "replaced by a new draft", user.id)
        soft_delete(db, old, user.id)
    created = create_from_proforma(db, proforma, user.id)
    if not created:
        raise HTTPException(status_code=400, detail="Nothing to invoice: no Billed by Clarus or paid-by-us charges on this proforma.")
    db.flush()
    for inv in created:
        record_change(db, "final_invoices", inv.id, "created", None, f"{inv.kind} from proforma {proforma_id}", user.id)
    db.commit()
    return [compute(i) for i in created]


@router.get("/shipments/{shipment_id}/final-invoices")
def list_final_invoices(shipment_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    rows = db.query(FinalInvoice).filter(FinalInvoice.shipment_id == shipment_id).order_by(FinalInvoice.id.desc()).all()
    return [compute(i) for i in rows]


@router.get("/final-invoices/{invoice_id}.pdf")
def final_invoice_pdf(invoice_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    inv = _get(db, invoice_id)
    data = compute(inv)
    number = (inv.number or f"DRAFT-{inv.id}").replace("/", "-")
    kind = "Tax Invoice" if inv.kind == "tax" else "Reimbursement Invoice"
    filename = f"{data['customer'].get('name') or 'Client'} - {number} - {kind}.pdf"
    return Response(content=render_final_pdf(data), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename",
    })


@router.get("/final-invoices/{invoice_id}")
def get_final_invoice(invoice_id: int, db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    return compute(_get(db, invoice_id))


@router.patch("/final-invoices/{invoice_id}")
def update_final_invoice(invoice_id: int, payload: FinalInvoiceUpdate, db: Session = Depends(get_db),
                         user: User = Depends(require_billing_access)):
    inv = _get(db, invoice_id)
    changes = payload.model_dump(exclude_unset=True, mode="json")
    if inv.status != "draft":
        locked = set(changes) - {"irn", "ack_no", "ack_date"}
        if locked:
            raise HTTPException(status_code=400, detail="This invoice is issued — only IRN / ACK can be filled in. "
                                                        "Cancel it and make a new one to change anything else.")
        if inv.status == "cancelled":
            raise HTTPException(status_code=400, detail="This invoice is cancelled.")
    for field, value in changes.items():
        if field in ("invoice_date", "due_date") and value:
            value = date.fromisoformat(value)
        if field == "header":
            value = {**(inv.header or {}), **value}
        if field == "customer":
            value = {**(inv.customer or {}), **value}
        old = getattr(inv, field)
        if old != value:
            record_change(db, "final_invoices", inv.id, field, old, value, user.id)
            setattr(inv, field, value)
    db.commit()
    db.refresh(inv)
    return compute(inv)


@router.post("/final-invoices/{invoice_id}/issue")
def issue_final_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """Number it (CL/<n>/<FY> or RI/CL/<n>/<FY>; the pair shares <n>) and lock it."""
    inv = _get(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(status_code=400, detail="Only a draft can be issued")
    if not inv.lines:
        raise HTTPException(status_code=400, detail="The invoice has no lines")
    if not (inv.customer or {}).get("gstin"):
        raise HTTPException(status_code=400, detail="Enter the customer's GSTIN first (place of supply depends on it)")
    issue(db, inv)
    record_change(db, "final_invoices", inv.id, "issued", None, inv.number, user.id)
    db.commit()
    db.refresh(inv)
    return compute(inv)


@router.post("/final-invoices/{invoice_id}/cancel")
def cancel_final_invoice(invoice_id: int, payload: Optional[CancelIn] = None, db: Session = Depends(get_db),
                         user: User = Depends(require_admin)):
    """Admin: cancel an issued invoice. It's kept, and its number is never reused."""
    inv = _get(db, invoice_id)
    if inv.status != "issued":
        raise HTTPException(status_code=400, detail="Only an issued invoice can be cancelled")
    inv.status = "cancelled"
    inv.cancelled_at = datetime.now()
    inv.cancelled_by_id = user.id
    inv.cancel_reason = ((payload.reason if payload else None) or "").strip() or None
    record_change(db, "final_invoices", inv.id, "cancelled", inv.number, None, user.id)
    db.commit()
    return compute(inv)


@router.delete("/final-invoices/{invoice_id}", status_code=204)
def delete_final_draft(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    inv = _get(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(status_code=400, detail="Only drafts can be deleted — cancel an issued invoice instead")
    record_change(db, "final_invoices", inv.id, "deleted", inv.kind, None, user.id)
    soft_delete(db, inv, user.id)  # never removed from the database (a trigger refuses DELETE)
    db.commit()


@router.get("/invoice-counter")
def get_counters(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    return {"counters": [{"fy": c.fy, "next_seq": c.next_seq} for c in db.query(InvoiceCounter).order_by(InvoiceCounter.fy)],
            "tax_types": TAX_TYPES}


@router.put("/invoice-counter")
def set_counter(payload: CounterIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Admin: where the invoice series continues from (e.g. after the last invoice made elsewhere)."""
    c = db.get(InvoiceCounter, payload.fy)
    old = c.next_seq if c else None
    if c is None:
        c = InvoiceCounter(fy=payload.fy, next_seq=payload.next_seq)
        db.add(c)
    else:
        c.next_seq = payload.next_seq
    record_change(db, "invoice_counters", 0, payload.fy, old, payload.next_seq, user.id)
    db.commit()
    return {"fy": c.fy, "next_seq": c.next_seq}

"""
Shipment invoice totals = sum over its invoices, per group.

CFS: a shipment can have several CFS invoices. Tax invoices are what's actually
payable, so when any tax invoice exists the totals are the sum of the tax
invoices; before that, the sum of the proformas (a proforma and the tax invoice
that replaces it are never added together).

Shipping line destination charges: same rule — tax invoices when any exist, else
proformas — using each invoice's cost inclusion part (-> the proforma's
"Cost Inclusion", or Reimbursement when the line is paid by us).
Receipts (CFS / shipping line) record what was actually paid; not part of these totals.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.enums import DocumentType
from app.models.document import ShipmentDocument
from app.models.shipment import Shipment

CFS_DOC_TYPES = (DocumentType.CFS_TAX_INVOICE, DocumentType.CFS_PROFORMA_INVOICE)
LINE_DOC_TYPES = (DocumentType.SHIPPING_LINE_INVOICE, DocumentType.SHIPPING_LINE_PROFORMA)
RECEIPT_DOC_TYPES = (DocumentType.CFS_RECEIPT, DocumentType.SHIPPING_LINE_RECEIPT)
# document types that carry before-tax / GST / total amounts
INVOICE_DOC_TYPES = CFS_DOC_TYPES + LINE_DOC_TYPES


def invoices_counted(docs: Iterable[ShipmentDocument]) -> list[ShipmentDocument]:
    """The CFS invoices that count towards the shipment's CFS totals."""
    docs = [d for d in docs if d.document_type in CFS_DOC_TYPES]
    tax = [d for d in docs if d.document_type == DocumentType.CFS_TAX_INVOICE]
    return tax or docs


def line_invoices_counted(docs: Iterable[ShipmentDocument]) -> list[ShipmentDocument]:
    """Shipping line invoices that count: tax invoices, or proformas until one arrives."""
    docs = [d for d in docs if d.document_type in LINE_DOC_TYPES]
    tax = [d for d in docs if d.document_type == DocumentType.SHIPPING_LINE_INVOICE]
    return tax or docs


def _sum(values: list) -> Optional[Decimal]:
    present = [Decimal(v) for v in values if v is not None]
    return sum(present, Decimal("0")) if present else None


def _add(a, b) -> Optional[Decimal]:
    return None if a is None and b is None else Decimal(a or 0) + Decimal(b or 0)


def invoice_charges(doc: ShipmentDocument) -> list[dict]:
    """Charge lines read from a shipping line invoice ([] if they didn't add up)."""
    fields = (doc.extraction or {}).get("fields") or {}
    return fields.get("charges") or [] if fields.get("charges_complete") else []


def cost_from_charges(doc: ShipmentDocument, excluded: Iterable[int]) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """(before tax, GST) of the invoice's charges minus the excluded ones. GST per
    charge when the invoice prints it, else the invoice's GST pro rata."""
    charges, out = invoice_charges(doc), set(excluded)
    kept = [c for i, c in enumerate(charges) if i not in out]
    before = sum((Decimal(str(c["amount"] or 0)) for c in kept), Decimal("0"))
    if all(c.get("gst") is not None for c in charges):
        gst = sum((Decimal(str(c["gst"])) for c in kept), Decimal("0"))
    elif doc.amount_before_tax:
        gst = (Decimal(doc.gst_amount or 0) * before / Decimal(doc.amount_before_tax)).quantize(Decimal("0.01"))
    else:
        gst = Decimal("0")
    return before, gst


def cost_inclusion(doc: ShipmentDocument) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """(before tax, GST) this shipping line invoice adds to the cost inclusion."""
    if doc.cost_before_tax is not None:
        return Decimal(doc.cost_before_tax), Decimal(doc.cost_gst or 0)
    return doc.amount_before_tax, doc.gst_amount


def default_cost_inclusion(doc: ShipmentDocument) -> None:
    """Client rule: a charge counts only if it's billed in INR AND its head isn't
    freight (see shipping_line_pdf). Sets cost_excluded / cost figures; leaves a
    hand-typed figure alone."""
    if doc.cost_manual:
        return
    excluded = [i for i, c in enumerate(invoice_charges(doc)) if c.get("in_cost_inclusion") is False]
    doc.cost_excluded = excluded or None
    doc.cost_before_tax, doc.cost_gst = cost_from_charges(doc, excluded) if excluded else (None, None)


def _apply(db: Session, shipment: Shipment, totals: dict, user_id: Optional[int]) -> None:
    for field, value in totals.items():
        old = getattr(shipment, field)
        if (old is None) != (value is None) or (old is not None and Decimal(old) != value):
            record_change(db, "shipments", shipment.id, field, old, value, user_id)
            setattr(shipment, field, value)


def recompute_invoice_totals(db: Session, shipment: Shipment, user_id: Optional[int]) -> None:
    """Set the shipment's CFS and shipping-line totals from its invoices (audit-logged)."""
    db.flush()
    docs = db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == shipment.id).all()
    cfs = invoices_counted(docs)
    line = line_invoices_counted(docs)
    _apply(db, shipment, {
        "cfs_amount_before_tax": _sum([d.amount_before_tax for d in cfs]),
        "cfs_gst_amount": _sum([d.gst_amount for d in cfs]),
        "cfs_amount_total": _sum([d.amount_total for d in cfs]),
        # cost inclusion part of each shipping line invoice (see cost_inclusion())
        "line_amount_before_tax": _sum([cost_inclusion(d)[0] for d in line]),
        "line_gst_amount": _sum([cost_inclusion(d)[1] for d in line]),
        "line_amount_total": _sum([_add(*cost_inclusion(d)) for d in line]),
    }, user_id)


# old name, still used in a few places
recompute_cfs_totals = recompute_invoice_totals

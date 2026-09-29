"""Payments & outstanding (P1, client 2026-09-30) — admin / billing only, like all invoicing."""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.models.final_invoice import FinalInvoice
from app.models.payment import Payment, PaymentAllocation
from app.models.soft_delete import soft_delete
from app.models.user import User
from app.receivables import invoice_state, receivables, settled_by_invoice

router = APIRouter(tags=["payments"], dependencies=[Depends(require_billing_access)])

MODES = ("NEFT", "RTGS", "IMPS", "Cheque", "UPI", "Cash", "Other")


class AllocationIn(BaseModel):
    invoice_id: int
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tds: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)


class PaymentIn(BaseModel):
    received_on: date
    party: str = Field(min_length=1, max_length=200)
    party_gstin: Optional[str] = Field(default=None, max_length=20)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    mode: Optional[str] = None
    reference: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)
    allocations: list[AllocationIn] = []


def _payment_out(p: Payment) -> dict:
    return {"id": p.id, "received_on": p.received_on.isoformat(), "party": p.party, "party_gstin": p.party_gstin,
            "amount": str(p.amount), "mode": p.mode, "reference": p.reference, "notes": p.notes,
            "allocations": [{"invoice_id": a.final_invoice_id, "number": a.invoice.number if a.invoice else None,
                             "amount": str(a.amount), "tds": str(a.tds)} for a in p.allocations],
            "unallocated": str(Decimal(p.amount) - sum((Decimal(a.amount) for a in p.allocations), Decimal("0")))}


@router.get("/receivables")
def list_receivables(include_paid: bool = False, client: Optional[str] = None, db: Session = Depends(get_db)):
    """Per client: billed, received, TDS, outstanding, ageing buckets and the open invoices."""
    return {"as_of": date.today().isoformat(), "clients": receivables(db, date.today(), include_paid, client)}


@router.get("/payments")
def list_payments(party: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Payment).order_by(Payment.received_on.desc(), Payment.id.desc())
    rows = [p for p in q if not party or party.lower() in p.party.lower()]
    return [_payment_out(p) for p in rows]


@router.post("/payments", status_code=201)
def record_payment(payload: PaymentIn, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """Record money received and set it against issued invoices (amount + TDS each can't exceed
    what's outstanding on it). Whatever isn't allocated stays on account."""
    if payload.mode and payload.mode not in MODES:
        raise HTTPException(status_code=422, detail=f"Mode must be one of {', '.join(MODES)}")
    allocated = sum((a.amount for a in payload.allocations), Decimal("0"))
    if allocated > payload.amount + Decimal("0.005"):
        raise HTTPException(status_code=400, detail="The split adds up to more than the amount received")
    ids = [a.invoice_id for a in payload.allocations]
    invs = {i.id: i for i in db.query(FinalInvoice).filter(FinalInvoice.id.in_(ids)).with_for_update()} if ids else {}
    settled = settled_by_invoice(db, ids)
    today = date.today()
    for a in payload.allocations:
        inv = invs.get(a.invoice_id)
        if inv is None or inv.status != "issued":
            raise HTTPException(status_code=400, detail="Payments can only be set against issued invoices")
        left = Decimal(invoice_state(inv, settled, today)["outstanding"])
        if a.amount + a.tds > left + Decimal("1"):
            raise HTTPException(status_code=400, detail=f"{inv.number}: only ₹{left:,.2f} is outstanding")
    p = Payment(received_on=payload.received_on, party=payload.party.strip(),
                party_gstin=(payload.party_gstin or "").strip().upper() or None, amount=payload.amount,
                mode=payload.mode, reference=(payload.reference or "").strip() or None, notes=payload.notes,
                created_by_id=user.id)
    p.allocations = [PaymentAllocation(final_invoice_id=a.invoice_id, amount=a.amount, tds=a.tds)
                     for a in payload.allocations if a.amount or a.tds]
    db.add(p)
    db.flush()
    record_change(db, "payments", p.id, "recorded", None,
                  f"₹{payload.amount} from {p.party} ({', '.join(invs[a.invoice_id].number for a in payload.allocations)})",
                  user.id)
    db.commit()
    db.refresh(p)
    return _payment_out(p)


@router.delete("/payments/{payment_id}", status_code=204)
def delete_payment(payment_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin: a payment entered by mistake. Soft-deleted (Recently deleted can restore it)."""
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    record_change(db, "payments", p.id, "deleted", str(p.amount), None, admin.id)
    soft_delete(db, p, admin.id)
    db.commit()


@router.get("/receivables/statement.pdf")
def statement(client: str, db: Session = Depends(get_db)):
    """Statement of account for one client: open invoices, what's received, what's outstanding."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table

    from app.invoice.company import company
    from app.invoice.pdf import BAR_C, HEAD_C, MARGIN, WIDTH, _p, _style

    rows = [c for c in receivables(db, date.today(), False, client)]
    if not rows:
        raise HTTPException(status_code=404, detail="Nothing outstanding for that client")
    c = rows[0]
    co = company()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
                            title=f"Statement - {c['party']}")
    inr = lambda v: f"{Decimal(v):,.2f}"  # noqa: E731
    head = [_p(co["name"], 14, True, colors.HexColor("#D26B21")), _p(co["address"], 7.5), _p(co["tax_line"], 7.5),
            Spacer(1, 8), _p("STATEMENT OF ACCOUNT", 12, True), _p(f"{c['party']}   {c['gstin']}", 9, True),
            _p(f"As of {date.today():%d %b %Y}", 8), Spacer(1, 8)]
    data = [[_p(h, 7.5, True) for h in ("Invoice", "Date", "BE No", "BL No", "Net payable", "Received", "TDS",
                                           "Outstanding", "Days")]]
    for i in c["invoices"]:
        data.append([_p(i["number"] or "", 7.5), _p(i["invoice_date"] or "", 7.5), _p(i["be_no"] or "", 7.5),
                     _p(i["mbl"] or "", 7),
                     _p(inr(i["net_payable"]), 7.5), _p(inr(i["paid"]), 7.5), _p(inr(i["tds"]), 7.5),
                     _p(inr(i["outstanding"]), 7.5, True), _p(str(i["age_days"]), 7.5)])
    data.append([_p("Total outstanding", 8, True), "", "", "", "", "", "", _p(inr(c["outstanding"]), 8.5, True), ""])
    t = Table(data, colWidths=[WIDTH * f for f in (0.15, 0.1, 0.09, 0.15, 0.12, 0.11, 0.08, 0.13, 0.07)], repeatRows=1)
    t.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDD")),
                      ("SPAN", (0, -1), (6, -1)), ("LINEABOVE", (0, -1), (-1, -1), 1, BAR_C)))
    ageing = [[_p(k + " days", 7.5, True) for k in c["buckets"]], [_p(inr(v), 8) for v in c["buckets"].values()]]
    at = Table(ageing, colWidths=[WIDTH / 4] * 4)
    at.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDD"))))
    doc.build([*head, t, Spacer(1, 10), _p("Ageing", 9, True), at])
    filename = f"Statement - {c['party']} - {date.today():%d-%b-%Y}.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename"})

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
from app.receivables import invoice_state, party_key, payment_key, receivables, settled_by_invoice

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
            "key": payment_key(p),
            # BE and BL with every invoice it paid — how the team finds a shipment (client, 2026-09-30)
            "allocations": [{"invoice_id": a.final_invoice_id, "number": a.invoice.number if a.invoice else None,
                             "shipment_id": a.invoice.shipment_id if a.invoice else None,
                             "job": a.invoice.shipment.job if a.invoice and a.invoice.shipment else None,
                             "be_no": ((a.invoice.header or {}).get("be_no") or (a.invoice.shipment.be_no if a.invoice.shipment else None))
                             if a.invoice else None,
                             "mbl": a.invoice.shipment.mbl if a.invoice and a.invoice.shipment else None,
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


class AllocateIn(BaseModel):
    allocations: list[AllocationIn] = Field(min_length=1)


def _check_allocations(db: Session, allocations: list[AllocationIn], key: Optional[str] = None) -> dict:
    """Each invoice must be issued (and, for money already received, this client's); amount + TDS
    can't exceed what's outstanding on it. Returns the invoices by id."""
    ids = [a.invoice_id for a in allocations]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="The same invoice is in the split twice")
    invs = {i.id: i for i in db.query(FinalInvoice).filter(FinalInvoice.id.in_(ids)).with_for_update()} if ids else {}
    settled = settled_by_invoice(db, ids)
    today = date.today()
    for a in allocations:
        inv = invs.get(a.invoice_id)
        if inv is None or inv.status != "issued":
            raise HTTPException(status_code=400, detail="Payments can only be set against issued invoices")
        if key and party_key(inv.customer or {}) != key:
            raise HTTPException(status_code=400, detail=f"{inv.number} is another client's invoice")
        left = Decimal(invoice_state(inv, settled, today)["outstanding"])
        if a.amount + a.tds > left + Decimal("1"):
            raise HTTPException(status_code=400, detail=f"{inv.number}: only ₹{left:,.2f} is outstanding")
    return invs


@router.post("/payments", status_code=201)
def record_payment(payload: PaymentIn, db: Session = Depends(get_db), user: User = Depends(require_billing_access)):
    """Record money received and set it against issued invoices (amount + TDS each can't exceed
    what's outstanding on it). Whatever isn't allocated stays on account."""
    if payload.mode and payload.mode not in MODES:
        raise HTTPException(status_code=422, detail=f"Mode must be one of {', '.join(MODES)}")
    allocated = sum((a.amount for a in payload.allocations), Decimal("0"))
    if allocated > payload.amount + Decimal("0.005"):
        raise HTTPException(status_code=400, detail="The split adds up to more than the amount received")
    invs = _check_allocations(db, payload.allocations)
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


@router.post("/payments/{payment_id}/allocate")
def allocate_payment(payment_id: int, payload: AllocateIn, db: Session = Depends(get_db),
                     user: User = Depends(require_billing_access)):
    """Set money already received (on account / an advance) against this client's invoices later."""
    p = db.query(Payment).filter(Payment.id == payment_id).with_for_update().first()
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    free = Decimal(p.amount) - sum((Decimal(a.amount) for a in p.allocations), Decimal("0"))
    wanted = sum((a.amount for a in payload.allocations), Decimal("0"))
    if wanted > free + Decimal("0.005"):
        raise HTTPException(status_code=400, detail=f"Only ₹{free:,.2f} of this payment is on account")
    invs = _check_allocations(db, payload.allocations, payment_key(p))
    have = {a.final_invoice_id: a for a in p.allocations}
    for a in payload.allocations:
        if not (a.amount or a.tds):
            continue
        if a.invoice_id in have:
            have[a.invoice_id].amount = Decimal(have[a.invoice_id].amount) + a.amount
            have[a.invoice_id].tds = Decimal(have[a.invoice_id].tds) + a.tds
        else:
            p.allocations.append(PaymentAllocation(final_invoice_id=a.invoice_id, amount=a.amount, tds=a.tds))
    record_change(db, "payments", p.id, "allocated", f"₹{free} on account",
                  ", ".join(f"{invs[a.invoice_id].number} ₹{a.amount}" + (f" + TDS ₹{a.tds}" if a.tds else "")
                            for a in payload.allocations), user.id)
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
    """Statement of account for one client: open invoices, payments received, money on account and
    what's outstanding. `client` is the client's key (gstin:… / name:…) — exactly one client — or,
    for older links, the client's full name."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table

    from app.invoice.company import company
    from app.invoice.pdf import BAR_C, HEAD_C, MARGIN, WIDTH, _p, _style

    key = client if client.startswith(("gstin:", "name:")) else None
    rows = receivables(db, date.today(), False, key=key) if key else \
        [c for c in receivables(db, date.today(), False) if c["party"].strip().upper() == client.strip().upper()]
    if len(rows) != 1:
        raise HTTPException(status_code=404, detail="Nothing outstanding for that client")
    c = rows[0]
    pays = [p for p in db.query(Payment).filter(Payment.deleted_at.is_(None)).order_by(Payment.received_on, Payment.id)
            if payment_key(p) == c["key"]]
    co = company()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
                            title=f"Statement - {c['party']}")
    inr = lambda v: f"{Decimal(v):,.2f}"  # noqa: E731
    day = lambda v: f"{date.fromisoformat(v) if isinstance(v, str) else v:%d-%b-%Y}" if v else ""  # noqa: E731
    grid = ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDD"))
    head = [_p(co["name"], 14, True, colors.HexColor("#D26B21")), _p(co["address"], 7.5), _p(co["tax_line"], 7.5),
            Spacer(1, 8), _p("STATEMENT OF ACCOUNT", 12, True), _p(f"{c['party']}   {c['gstin']}", 9, True),
            _p(f"As of {date.today():%d-%b-%Y}", 8), Spacer(1, 8)]
    data = [[_p(h, 7.5, True) for h in ("Invoice", "Date", "BE No", "BL No", "Net payable", "Received", "TDS",
                                           "Outstanding", "Days")]]
    for i in c["invoices"]:
        data.append([_p(i["number"] or "", 7.5), _p(day(i["invoice_date"]), 7.5), _p(i["be_no"] or "", 7.5),
                     _p(i["mbl"] or "", 7),
                     _p(inr(i["net_payable"]), 7.5), _p(inr(i["paid"]), 7.5), _p(inr(i["tds"]), 7.5),
                     _p(inr(i["outstanding"]), 7.5, True), _p(str(i["age_days"]), 7.5)])
    data.append([_p("Total outstanding", 8, True), "", "", "", "", "", "", _p(inr(c["outstanding"]), 8.5, True), ""])
    summary = 1
    if Decimal(c["on_account"]) > 0:
        data.append([_p("Less: received on account, not yet set against an invoice", 8), "", "", "", "", "", "",
                     _p(f"- {inr(c['on_account'])}", 8.5), ""])
        data.append([_p("Balance payable", 8, True), "", "", "", "", "", "",
                     _p(inr(max(Decimal(0), Decimal(c["outstanding"]) - Decimal(c["on_account"]))), 8.5, True), ""])
        summary = 3
    t = Table(data, colWidths=[WIDTH * f for f in (0.15, 0.1, 0.09, 0.15, 0.12, 0.11, 0.08, 0.13, 0.07)], repeatRows=1)
    t.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), grid,
                      *[("SPAN", (0, -r), (6, -r)) for r in range(1, summary + 1)],
                      ("LINEABOVE", (0, -summary), (-1, -summary), 1, BAR_C)))
    ageing = [[_p(k + " days", 7.5, True) for k in c["buckets"]], [_p(inr(v), 8) for v in c["buckets"].values()]]
    at = Table(ageing, colWidths=[WIDTH / 4] * 4)
    at.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDD"))))
    story = [*head, t, Spacer(1, 10), _p("Ageing", 9, True), at]
    if pays:
        pd = [[_p(h, 7.5, True) for h in ("Received on", "Amount", "Mode", "Reference", "Set against", "On account")]]
        for p in pays:
            out = _payment_out(p)
            against = ", ".join(f"{a['number']} {inr(a['amount'])}" + (f" + TDS {inr(a['tds'])}" if Decimal(a["tds"]) else "")
                                for a in out["allocations"]) or "—"
            pd.append([_p(day(p.received_on), 7.5), _p(inr(p.amount), 7.5), _p(p.mode or "", 7.5), _p(p.reference or "", 7),
                       _p(against, 7), _p(inr(out["unallocated"]) if Decimal(out["unallocated"]) else "—", 7.5)])
        pt = Table(pd, colWidths=[WIDTH * f for f in (0.12, 0.13, 0.09, 0.16, 0.37, 0.13)], repeatRows=1)
        pt.setStyle(_style(("BACKGROUND", (0, 0), (-1, 0), HEAD_C), grid))
        story += [Spacer(1, 10), _p("Payments received", 9, True), pt]
    doc.build(story)
    filename = f"Statement - {c['party']} - {date.today():%d-%b-%Y}.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Filename": quote(filename), "Access-Control-Expose-Headers": "X-Filename"})

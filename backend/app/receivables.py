"""
Payments & outstanding (client, 2026-09-30, P1).

An issued final invoice is settled by the payments allocated to it (amount + any TDS the client
deducted). Outstanding = net payable − settled. Cancelled invoices and "not applicable" ones
(₹0) never count. Ageing is from the invoice date: 0-30 / 31-60 / 61-90 / 90+ days.
Clients are grouped by GSTIN (else by name).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.invoice.final import compute
from app.models.final_invoice import FinalInvoice
from app.models.payment import Payment, PaymentAllocation

ZERO = Decimal("0")
TDS_RATE = Decimal("0.02")  # 194C, contractor
BUCKETS = (("0-30", 30), ("31-60", 60), ("61-90", 90), ("90+", None))


def party_key(customer: dict) -> str:
    gstin = (customer.get("gstin") or "").strip().upper()
    return f"gstin:{gstin}" if gstin else f"name:{(customer.get('name') or '').strip().upper()}"


def settled_by_invoice(db: Session, invoice_ids: Optional[Iterable[int]] = None) -> dict[int, dict]:
    """{invoice id: {"paid": amount, "tds": tds}} from payments that aren't deleted."""
    q = db.query(PaymentAllocation).join(Payment).filter(Payment.deleted_at.is_(None))
    if invoice_ids is not None:
        q = q.filter(PaymentAllocation.final_invoice_id.in_(list(invoice_ids)))
    out: dict[int, dict] = defaultdict(lambda: {"paid": ZERO, "tds": ZERO})
    for a in q:
        out[a.final_invoice_id]["paid"] += Decimal(a.amount or 0)
        out[a.final_invoice_id]["tds"] += Decimal(a.tds or 0)
    return out


def bucket(days: int) -> str:
    for name, upto in BUCKETS:
        if upto is None or days <= upto:
            return name
    return "90+"


def payment_key(p: Payment) -> str:
    return f"gstin:{p.party_gstin.strip().upper()}" if p.party_gstin else f"name:{p.party.strip().upper()}"


def invoice_state(inv: FinalInvoice, settled: dict, today: date) -> dict:
    d = compute(inv)
    net = Decimal(d["totals"]["net_payable"])
    s = settled.get(inv.id, {"paid": ZERO, "tds": ZERO})
    done = s["paid"] + s["tds"]
    outstanding = max(ZERO, net - done)
    # TDS (194C) is cut on our service (tax) invoice only, never on reimbursements (client, 2026-09-30)
    tds_expected = bool(inv.kind == "tax" and inv.shipment and inv.shipment.tds_deducted)
    # what the client will likely hold back: ~2% of the taxable value, until some TDS is recorded
    tds_estimate = ZERO
    if tds_expected and s["tds"] == 0 and outstanding > 0:
        tds_estimate = min(outstanding, (Decimal(d["totals"]["sub_taxable"]) * TDS_RATE).quantize(Decimal("0.01")))
    days = (today - inv.invoice_date).days if inv.invoice_date else 0
    status = "paid" if net > 0 and outstanding < Decimal("1") else ("part-paid" if done > 0 else "unpaid")
    return {
        "id": inv.id, "number": inv.number, "kind": inv.kind, "invoice_date": d["invoice_date"],
        "customer": d["customer"].get("name") or "", "gstin": d["customer"].get("gstin") or "",
        "shipment_id": inv.shipment_id, "job": inv.shipment.job if inv.shipment else None,
        # BE and BL on every row — how the team finds a shipment (client, 2026-09-30)
        "be_no": (inv.header or {}).get("be_no") or (inv.shipment.be_no if inv.shipment else None),
        "mbl": inv.shipment.mbl if inv.shipment else None,
        "tds_expected": tds_expected, "tds_estimate": str(tds_estimate),
        "net_payable": str(net), "paid": str(s["paid"]), "tds": str(s["tds"]), "outstanding": str(outstanding),
        "pay_status": status if net > 0 else "not applicable", "age_days": days, "bucket": bucket(days),
    }


def open_invoices(db: Session, today: date) -> list[FinalInvoice]:
    return [i for i in db.query(FinalInvoice).filter(FinalInvoice.status == "issued").all()
            if not ((i.header or {}).get("not_applicable") and not i.lines)]


def receivables(db: Session, today: date, include_paid: bool = False, client: Optional[str] = None,
                key: Optional[str] = None) -> list[dict]:
    """`client` narrows by part of the name (the filter box); `key` picks exactly one client (party_key)."""
    invs = open_invoices(db, today)
    settled = settled_by_invoice(db, [i.id for i in invs])
    clients: dict[str, dict] = {}
    for inv in invs:
        st = invoice_state(inv, settled, today)
        k = party_key(inv.customer or {})
        if client and client.lower() not in st["customer"].lower():
            continue
        if key and k != key:
            continue
        c = clients.setdefault(k, {
            "key": k, "party": st["customer"], "gstin": st["gstin"], "billed": ZERO, "received": ZERO, "tds": ZERO,
            "outstanding": ZERO, "tds_estimate": ZERO, "buckets": {b: ZERO for b, _ in BUCKETS}, "oldest_days": 0,
            "invoices": []})
        c["billed"] += Decimal(st["net_payable"])
        c["received"] += Decimal(st["paid"])
        c["tds"] += Decimal(st["tds"])
        out = Decimal(st["outstanding"])
        c["outstanding"] += out
        c["tds_estimate"] += Decimal(st["tds_estimate"])
        if out > 0:
            c["buckets"][st["bucket"]] += out
            c["oldest_days"] = max(c["oldest_days"], st["age_days"])
        if include_paid or out > 0:
            c["invoices"].append(st)
    # on-account money (received, not yet set against an invoice) — the client owes that much less
    for p in db.query(Payment).filter(Payment.deleted_at.is_(None)).all():
        pk = payment_key(p)
        extra = Decimal(p.amount) - sum((Decimal(a.amount or 0) for a in p.allocations), ZERO)
        if pk in clients and extra > 0:
            clients[pk]["on_account"] = clients[pk].get("on_account", ZERO) + extra
    rows = [c for c in clients.values() if include_paid or c["outstanding"] > 0]
    for c in rows:
        c["invoices"].sort(key=lambda r: (r["invoice_date"] or "", r["number"] or ""))
        # net due = outstanding − money already on account − TDS the client will likely hold back
        c["net_due"] = max(ZERO, c["outstanding"] - c.get("on_account", ZERO) - c["tds_estimate"])
        for k in ("billed", "received", "tds", "outstanding", "on_account", "tds_estimate", "net_due"):
            c[k] = str(c.get(k, ZERO))
        c["buckets"] = {k: str(v) for k, v in c["buckets"].items()}
    return sorted(rows, key=lambda c: Decimal(c["outstanding"]), reverse=True)

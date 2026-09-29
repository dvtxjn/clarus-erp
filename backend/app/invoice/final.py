"""
Final invoices (tax / reimbursement) made from a proforma — see models/final_invoice.py.

Laid out like the client's current invoices (samples CL/200/26-27 and RI/CL/200/26-27):
customer block with PAN / GSTIN / state, place of supply, job no, the shipment block
(BE / MBL / HBL / vessel / values), lines with SAC and tax type (T taxable, P pure
agent, E exempt, R reverse charge, N non-taxable), SAC summary, totals down to net
payable and amount in words. GST is IGST when the customer's state differs from ours
(27, Maharashtra), else CGST + SGST half each.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.enums import ChargeCategory
from app.invoice.build import (
    GST_DIFFERENCE_CODE, bill_to_organization, bill_to_name, container_count,
)
from app.invoice.company import BANK, COMPANY, TERMS
from app.models.final_invoice import FinalInvoice, InvoiceCounter
from app.models.proforma import Proforma

ZERO = Decimal("0")
KINDS = ("tax", "reimbursement")
TITLES = {"tax": "TAX INVOICE", "reimbursement": "REIMBURSEMENT INVOICE"}
TAX_TYPES = {"T": "Taxable", "P": "Pure Agent", "E": "Exemption", "R": "Reverse Charge", "N": "Non Taxable"}

# GST state codes
STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}

# the shipment block, in print order: (key, label) — only what the client needs (2026-09-28)
HEADER_FIELDS = [
    ("be_no", "BE Number"), ("be_date", "BE Date"), ("mbl_no", "MBL No."), ("hbl_no", "HBL No."),
    ("no_of_containers", "No. of Containers"), ("origin_port", "Port of Origin"),
]


def fy_of(d: date) -> str:
    """Indian financial year (April-March): 15-Sep-2026 -> '26-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def number_for(kind: str, seq: int, fy: str) -> str:
    return f"CL/{seq}/{fy}" if kind == "tax" else f"RI/CL/{seq}/{fy}"


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v).replace(",", "")) if v not in (None, "") else ZERO
    except ArithmeticError:
        return ZERO


def _money(v: Decimal) -> str:
    return str(Decimal(v).quantize(Decimal("0.01"), ROUND_HALF_UP))


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _three(n: int) -> str:
    h, rest = divmod(n, 100)
    return " ".join(x for x in ((_ONES[h] + " Hundred") if h else "", _two(rest) if rest else "") if x)


def _below_crore(n: int) -> str:
    lakh, n = divmod(n, 10 ** 5)
    thousand, n = divmod(n, 1000)
    parts = [f"{_two(lakh)} Lakh" if lakh else "", f"{_two(thousand)} Thousand" if thousand else "", _three(n) if n else ""]
    return " ".join(p for p in parts if p)


def in_words(amount: Decimal) -> str:
    """Indian system: 1436691 -> 'Fourteen Lakh Thirty Six Thousand Six Hundred Ninety One Only.'"""
    rupees = int(Decimal(amount).quantize(Decimal("1"), ROUND_HALF_UP))
    if rupees == 0:
        return "Zero Only."
    crore, rest = divmod(rupees, 10 ** 7)
    parts = [f"{_below_crore(crore) if crore >= 1000 else _three(crore)} Crore" if crore else "", _below_crore(rest)]
    return " ".join(p for p in parts if p) + " Only."


def _job_number(job: Optional[str], d: date) -> Optional[str]:
    """Tracker job '165' -> 'IMP/0165/26-27' (as on the client's invoices)."""
    m = re.search(r"\d+", job or "")
    return f"IMP/{int(m.group()):04d}/{fy_of(d)}" if m else None


def _customer(db: Session, proforma: Proforma) -> dict:
    org = bill_to_organization(proforma, db)
    gstin = (org.gstin if org else None) or ""
    code = gstin[:2] if re.match(r"^\d{2}", gstin) else None
    return {
        "name": (org.name if org else None) or bill_to_name(proforma) or "",
        "address": (org.address if org else None) or "",
        "pan": (org.pan if org else None) or (gstin[2:12] if len(gstin) >= 12 else ""),
        "gstin": gstin,
        "state_code": code or "",
        "state_name": STATES.get(code or "", (org.state if org else None) or ""),
    }


def _header(db: Session, proforma: Proforma, d: date) -> dict:
    s = proforma.shipment
    parts = [p.strip() for p in (s.mbl or "").split("/") if p.strip()]
    n = container_count(s)
    return {
        "job_number": _job_number(s.job, d), "job_type": "Sea Import",
        "be_no": s.be_no, "be_date": s.be_dt.strftime("%d-%b-%Y") if s.be_dt else None,
        "mbl_no": parts[0] if parts else s.mbl, "hbl_no": s.hbl or (parts[1] if len(parts) > 1 else None),
        "no_of_containers": str(n) if n else None, "origin_port": None,
    }


def lines_for(proforma: Proforma, kind: str) -> list[dict]:
    """Tax invoice: the Billed by Clarus lines (taxable, our GST). Reimbursement invoice:
    the Reimbursement lines — charges paid by us — as pure agent, no GST, at their full
    amount incl. the GST paid (e.g. Customs Duty = total duty). Royalty, Cost Inclusion
    and the GST Difference line are not invoiced by Clarus."""
    out = []
    for li in sorted(proforma.line_items, key=lambda x: (x.sort_order, x.id)):
        code = li.charge.code if li.charge else None
        if kind == "tax" and li.category == ChargeCategory.SERVICE:
            out.append({"description": li.description, "sub_description": None, "sac": li.sac_code, "tax_type": "T",
                        "non_gst_value": "0", "taxable_value": _money(li.amount),
                        "gst_rate": str(Decimal(li.gst_rate).normalize())})
        elif kind == "reimbursement" and li.category == ChargeCategory.REIMBURSEMENT and code != GST_DIFFERENCE_CODE:
            out.append({"description": li.description, "sub_description": None, "sac": li.sac_code, "tax_type": "P",
                        "non_gst_value": _money(li.total), "taxable_value": "0", "gst_rate": "0"})
    return out


NOT_APPLICABLE = "BILL CANCELLED — NOT APPLICABLE"


def create_from_proforma(db: Session, proforma: Proforma, user_id: Optional[int]) -> list[FinalInvoice]:
    """Draft tax + reimbursement invoices — always both, so the pair keeps one number
    (client, 2026-09-30). A kind with no charges is still made: every detail but no charge
    heads, marked "BILL CANCELLED — NOT APPLICABLE", so the numbering never breaks.
    Nothing at all to invoice: none made."""
    today = date.today()
    per_kind = {kind: lines_for(proforma, kind) for kind in KINDS}
    if not any(per_kind.values()):
        return []
    created = []
    for kind, lines in per_kind.items():
        header = _header(db, proforma, today)
        if not lines:
            header["not_applicable"] = True
        inv = FinalInvoice(shipment_id=proforma.shipment_id, proforma_id=proforma.id, kind=kind, status="draft",
                           invoice_date=today, due_date=today, customer=_customer(db, proforma),
                           header=header, lines=lines, advance_received=ZERO,
                           created_by_id=user_id)
        db.add(inv)
        created.append(inv)
    return created


def issue(db: Session, inv: FinalInvoice) -> None:
    """Give the number and lock. The tax / reimbursement pair made from one proforma
    shares its number (CL/200/26-27 and RI/CL/200/26-27)."""
    d = inv.invoice_date or date.today()
    fy = fy_of(d)
    sibling = db.query(FinalInvoice).filter(FinalInvoice.proforma_id == inv.proforma_id, FinalInvoice.id != inv.id,
                                            FinalInvoice.fy == fy, FinalInvoice.seq.isnot(None)).first() \
        if inv.proforma_id else None
    if sibling is not None:
        seq = sibling.seq
    else:
        counter = db.get(InvoiceCounter, fy)
        if counter is None:
            counter = InvoiceCounter(fy=fy, next_seq=1)
            db.add(counter)
        seq = counter.next_seq
        counter.next_seq = seq + 1
    inv.seq, inv.fy, inv.number = seq, fy, number_for(inv.kind, seq, fy)
    inv.status, inv.issued_at = "issued", datetime.now()


def alter_until(inv: FinalInvoice) -> Optional[date]:
    """An issued invoice can be altered until the 10th of the month after its invoice month
    (the GSTR-1 for that month is filed on the 11th) — September bills until 10 October
    (client, 2026-09-30)."""
    d = inv.invoice_date
    if d is None:
        return None
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, 10)


def compute(inv: FinalInvoice) -> dict:
    """Everything printed: per-line GST split, SAC summary, totals, words."""
    intra = (inv.customer or {}).get("state_code") == COMPANY["state_code"]
    lines, sac = [], {}
    sub_non = sub_taxable = sub_tax = ZERO
    for i, ln in enumerate(inv.lines or [], start=1):
        non, taxable, rate = _d(ln.get("non_gst_value")), _d(ln.get("taxable_value")), _d(ln.get("gst_rate"))
        tax = (taxable * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        half = (tax / 2).quantize(Decimal("0.01"), ROUND_HALF_UP)
        total = non + taxable + tax
        lines.append({**ln, "sr": i, "non_gst_value": _money(non), "taxable_value": _money(taxable),
                      "gst_rate": str(rate.normalize()), "tax": _money(tax),
                      "cgst": _money(half) if intra else None, "sgst": _money(tax - half) if intra else None,
                      "igst": None if intra else _money(tax), "total": _money(total)})
        sub_non, sub_taxable, sub_tax = sub_non + non, sub_taxable + taxable, sub_tax + tax
        if taxable:
            k = (ln.get("sac") or "", str(rate.normalize()))
            s = sac.setdefault(k, {"sac": k[0], "rate": k[1], "taxable": ZERO, "tax": ZERO})
            s["taxable"] += taxable
            s["tax"] += tax
    before_tax = sub_non + sub_taxable
    total = before_tax + sub_tax
    advance = _d(inv.advance_received)
    exact = total - advance
    net = exact.quantize(Decimal("1"), ROUND_CEILING)  # never round down (client)
    return {
        "id": inv.id, "kind": inv.kind, "title": TITLES[inv.kind], "status": inv.status, "number": inv.number,
        # no charges of this kind: issued anyway (keeps the pair's number), marked across the bill
        "not_applicable": bool((inv.header or {}).get("not_applicable")) and not inv.lines,
        "alter_until": alter_until(inv).isoformat() if inv.status == "issued" and alter_until(inv) else None,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "customer": inv.customer or {},
        "place_of_supply": f"[{int(inv.customer['state_code'])}] {inv.customer.get('state_name', '')}"
        if (inv.customer or {}).get("state_code", "").isdigit() else "",
        "intra_state": intra, "header": inv.header or {}, "header_fields": HEADER_FIELDS,
        "lines": lines, "remarks": inv.remarks, "irn": inv.irn, "ack_no": inv.ack_no, "ack_date": inv.ack_date,
        "sac_summary": [{**v, "taxable": _money(v["taxable"]), "tax": _money(v["tax"])} for v in sac.values()],
        "totals": {
            "sub_non_gst": _money(sub_non), "sub_taxable": _money(sub_taxable), "sub_tax": _money(sub_tax),
            "sub_total": _money(total), "before_tax": _money(before_tax), "gst": _money(sub_tax),
            "invoice_value": _money(total), "advance_received": _money(advance),
            "round_off": _money(net - exact), "net_payable": _money(net), "reverse_charge": "0.00",
            "in_words": in_words(net),
        },
        "company": COMPANY, "bank": BANK, "terms": TERMS, "proforma_id": inv.proforma_id,
        "shipment_id": inv.shipment_id,
    }

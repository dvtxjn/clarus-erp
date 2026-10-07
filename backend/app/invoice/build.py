"""
Proforma invoice = one data structure, rendered three ways (screen, Excel, PDF)
so they always agree. Layout follows the client's template, but the charge
rows are dynamic (any number of lines per section) instead of fixed cells.

Sections (ChargeCategory):
  SERVICE        "Billed by Clarus"            our fees + our GST
  REIMBURSEMENT  "Reimbursement (at actuals)"  paid on the client's behalf, actual GST
  COST_INCLUSION "Cost Inclusion"              shipping line — shown, NOT in the total
Grand total payable to Clarus = Billed by Clarus + Reimbursement.

Template formulas (client's .xlsm, confirmed 2026-09-28):
  Customs Duty   total = BE total duty + interest (from the duty challan);
                 GST column = IGST; basic = total - IGST
  Stamp Duty     INMUN1: ROUNDDOWN(0.1% x assessable)
                 INNSA1: CEILING(0.1% x (assessable + customs duty total))
                 other ports (ICDs / dry ports): none
  CFS            total rounded up to the rupee (grand total rounded to the rupee)
  Value of goods = assessable + every line's basic amount (incl. cost inclusion)
  GST input      = every line's GST;   Value/kg = value / weight (kg)
  GST output     = 18% x bill rate x weight;  GST Difference = max(0, output - input)
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session, object_session

from app.core.enums import ChargeCategory, DocumentType
from app.invoice.company import bank as company_bank, company as company_details, notes as proforma_notes
from app.models.challan import DutyChallan, ist_day, today_ist
from app.models.organization import OrganizationEntry
from app.models.proforma import Proforma, ProformaLineItem
from app.models.shipment import Shipment

SECTION_TITLES = {
    ChargeCategory.SERVICE: "Billed by Clarus",
    ChargeCategory.REIMBURSEMENT: "Reimbursement (at actuals)",
    ChargeCategory.ROYALTY: "Royalty",
    ChargeCategory.COST_INCLUSION: "Cost Inclusion",
}
ZERO = Decimal("0")
GST_OUTPUT_RATE = Decimal("0.18")
GST_DIFFERENCE_CODE = "GSTD"
# totals the template rounds up to the rupee. Royalty is NOT rounded per line: the two
# HSS copies split it differently, and only the grand total is rounded (round_off),
# so both copies end on the same amount (client, 2026-09-28).
CEILING_CODES = {"CFS"}


def container_count(shipment: Optional[Shipment]) -> Optional[int]:
    m = re.search(r"\d+", (shipment.container or "") if shipment else "")
    return int(m.group()) if m and int(m.group()) > 0 else None


def weight_kgs(shipment: Shipment) -> Optional[Decimal]:
    """Tracker keeps '84.885 MTS'; the invoice shows KGS like the BE."""
    m = re.search(r"[\d.]+", shipment.gross_wt or "")
    if not m:
        return None
    value = Decimal(m.group())
    return (value * 1000).quantize(Decimal("1")) if "MT" in (shipment.gross_wt or "").upper() else value


def stamp_duty(shipment: Shipment, customs_duty_total: Optional[Decimal] = None) -> Optional[Decimal]:
    """Mundra (INMUN1) = ROUNDDOWN(0.1% x assessable value); Nhava Sheva (INNSA1) =
    CEILING(0.1% x (assessable value + customs duty total incl. interest)).
    Other ports (ICDs / dry ports) = 0. None = can't work it out yet."""
    if shipment.assessable_value is None or not shipment.port:
        return None
    av = Decimal(shipment.assessable_value)
    if shipment.port == "INMUN1":
        return (av * Decimal("0.001")).quantize(Decimal("1"), ROUND_DOWN)
    if shipment.port == "INNSA1":
        duty = customs_duty_total if customs_duty_total is not None else Decimal(shipment.duty_amount or 0)
        return Decimal(math.ceil((av + duty) * Decimal("0.001")))
    return ZERO


_CHALLAN_DATE_FORMATS = ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d.%m.%y", "%d/%m/%y")


def challan_be_date(text: Optional[str]) -> Optional[date]:
    """DutyChallan.be_date is text as the export / ICEGATE gave it ("26.09.2026"); None = no/unreadable date."""
    raw = str(text or "").strip().split(" ")[0]
    for fmt in _CHALLAN_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def latest_challan(db: Session, be_no: Optional[str], be_date: Optional[date] = None) -> Optional[DutyChallan]:
    """A BE's most recent challan row. BE numbers are reused every year (client, 2026-09-30), so with the
    BE date: rows for that date first; rows without a (readable) date are the fallback; other dates never."""
    if not be_no:
        return None
    rows = (db.query(DutyChallan).filter(DutyChallan.be_no == be_no.strip())
            .order_by(DutyChallan.listed_at.desc().nullslast(), DutyChallan.uploaded_at.desc(), DutyChallan.id.desc()))
    if be_date is None:
        return rows.first()
    undated = None
    for ch in rows:
        d = challan_be_date(ch.be_date)
        if d == be_date:
            return ch
        if d is None and undated is None:
            undated = ch
    return undated


def _doc_amount(shipment: Shipment, doc_type: DocumentType, key: str) -> Optional[Decimal]:
    """An amount read from the latest document of this type (e.g. the OOC copy's total duty)."""
    for d in sorted((d for d in shipment.documents if d.document_type == doc_type), key=lambda d: d.id, reverse=True):
        raw = ((d.extraction or {}).get("fields") or {}).get(key)
        try:
            return Decimal(str(raw).replace(",", "")) if raw not in (None, "") else None
        except ArithmeticError:
            continue
    return None


def customs_duty(shipment: Shipment, challan: Optional[DutyChallan]) -> Optional[dict]:
    """{total, gst, basic, interest, source}. Customs duty total, by what's available:
      1. duty challan: BE total duty + interest (interest = Due Amount - BE duty, never < 0)
      2. OOC copy (no challan): its total amount — the final amount paid; interest =
         OOC total - assessed BE total
      3. the BE's total duty
    GST = IGST; basic = total - GST."""
    assessed = _doc_amount(shipment, DocumentType.ASSESSED_BILL_OF_ENTRY, "tot_amount")
    ooc = _doc_amount(shipment, DocumentType.OOC_BILL_OF_ENTRY, "tot_amount")
    duty = assessed if assessed is not None else (
        Decimal(shipment.duty_amount) if shipment.duty_amount is not None else None)
    interest = ZERO
    if challan is not None:
        source = "challan"
        if duty is not None:
            interest = max(ZERO, Decimal(challan.due_amount) - duty)
            total = duty + interest
        else:
            total = Decimal(challan.due_amount)
    elif ooc is not None:
        source, total = "ooc", ooc
        if assessed is not None:
            interest = max(ZERO, ooc - assessed)
    elif duty is not None:
        source, total = "be", duty
    else:
        return None
    gst = Decimal(shipment.igst_amount or 0)
    return {"total": total, "gst": gst, "basic": total - gst, "interest": interest, "source": source}


def _norm(name: Optional[str]) -> str:
    """Compare names loosely: case, punctuation, 'PRIVATE LIMITED' vs 'PVT LTD', 'M/S'."""
    n = re.sub(r"[^A-Z0-9]+", " ", (name or "").upper())
    n = re.sub(r"\bPRIVATE\b", "PVT", n)
    n = re.sub(r"\bLIMITED\b", "LTD", n)
    n = re.sub(r"^\s*M S\b", "", n)
    return " ".join(n.split())


def match_organization(db: Session, name: Optional[str]) -> Optional[OrganizationEntry]:
    """Organization repository entry for a tracker name like 'Mahrishi':
    exact name, one of its short names, or a unique entry whose name starts
    with it ('MAHRISHI RECYCLERS')."""
    key = _norm(name)
    if not key:
        return None
    orgs = db.query(OrganizationEntry).filter(OrganizationEntry.is_active.is_(True)).all()
    for o in orgs:
        if _norm(o.name) == key or key in {_norm(x) for x in (o.short_names or "").split(",")}:
            return o
    starts = [o for o in orgs if (_norm(o.name) + " ").startswith(key + " ")]
    return starts[0] if len(starts) == 1 else None


def bill_to_name(proforma: Proforma) -> Optional[str]:
    """Bill To is always the BE importer (name printed on the BE). Until a BE
    has been read: the tracker's party (HSS buyer / consignee)."""
    s = proforma.shipment
    return be_importer_name(s) or proforma.bill_to or s.consignee


def bill_to_organization(proforma: Proforma, db: Optional[Session] = None) -> Optional[OrganizationEntry]:
    """Organization repository entry for the Bill To details: picked on the
    proforma, else matched on the BE importer's name."""
    db = db or object_session(proforma)
    if proforma.bill_to_org_id:
        return db.get(OrganizationEntry, proforma.bill_to_org_id)
    return match_organization(db, bill_to_name(proforma))


def bl_consignee_organization(db: Session, shipment: Shipment) -> Optional[OrganizationEntry]:
    """BL consignee = the organization whose AD code is printed on the BE. Group companies
    can share an AD code (Earthman / Earthstar): then the one whose name matches the
    tracker's HSS seller / consignee."""
    ad = be_ad_code(shipment)
    if not ad:
        return None
    orgs = db.query(OrganizationEntry).filter(OrganizationEntry.ad_code == ad).all()
    if len(orgs) > 1:
        hints = [_norm(x) for x in (shipment.hss_seller, shipment.consignee) if x]
        for o in orgs:
            name = _norm(o.name)
            if any(h and (name.startswith(h.split()[0]) or h.startswith(name.split()[0])) for h in hints):
                return o
    return orgs[0] if orgs else None


def _is_gst_difference(li: ProformaLineItem) -> bool:
    return li.charge is not None and li.charge.code == GST_DIFFERENCE_CODE


def round_off(amount: Decimal) -> tuple[Decimal, Decimal]:
    """(grand total rounded UP to the next rupee, round-off). Lines keep their exact paise;
    only the final figure is rounded, so paise differences in GST (e.g. between the
    two HSS copies) never change the amount payable (client, 2026-09-28)."""
    rounded = Decimal(amount).quantize(Decimal("1"), ROUND_CEILING)  # never down: 7,20,403.40 -> 7,20,404 (+0.60)
    return rounded, rounded - Decimal(amount)


BILL_RATE_MARGIN = Decimal("0.10")  # automatic rate: at least 10 paise above value / kg
BILL_RATE_STEP = Decimal("0.25")    # and a standard-looking rate: next 25 paise step


def bill_rate_minimum(value_per_kg: Optional[Decimal], gst_input: Decimal, weight: Optional[Decimal]) -> Optional[Decimal]:
    """The automatic rate's floor: 10 paise over the value per kg, and enough that the
    GST difference isn't negative."""
    if value_per_kg is None or not weight:
        return None
    return max(value_per_kg + BILL_RATE_MARGIN, gst_input / (GST_OUTPUT_RATE * weight) + Decimal("0.01"))


def bill_rate_allowed(rate: Decimal, value_per_kg: Optional[Decimal], gst_input: Decimal,
                      weight: Optional[Decimal]) -> bool:
    """A rate typed by hand (client, 2026-10-07): no 10 paise margin — anything above the
    value per kg that leaves a GST difference above zero."""
    if value_per_kg is None or not weight:
        return True
    output = (GST_OUTPUT_RATE * rate * weight).quantize(Decimal("0.01"))
    return rate > value_per_kg and output - gst_input > 0


def lowest_bill_rate(value_per_kg: Optional[Decimal], gst_input: Decimal, weight: Optional[Decimal]) -> Optional[Decimal]:
    """The lowest rate (to the paisa) a hand-typed rate may be: the smallest GST difference
    above zero without going below the value per kg (client, 2026-10-07)."""
    if value_per_kg is None or not weight:
        return None
    floor = max(value_per_kg, gst_input / (GST_OUTPUT_RATE * weight))
    rate = floor.quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    while not bill_rate_allowed(rate, value_per_kg, gst_input, weight):
        rate += Decimal("0.01")
    return rate


def suggest_bill_rate(value_per_kg: Optional[Decimal], gst_input: Decimal, weight: Optional[Decimal]) -> Optional[Decimal]:
    """HSS bill rate (client, 2026-09-28): a little over the value per kg — at least
    10 paise above it and enough for a positive GST difference (18% x rate x weight >
    GST input) — rounded UP to the next 25 paise so it looks like a standard rate.
    11.80 -> 12.00; 12.15 -> 12.25."""
    minimum = bill_rate_minimum(value_per_kg, gst_input, weight)
    if minimum is None:
        return None
    steps = (minimum / BILL_RATE_STEP).to_integral_value(rounding=ROUND_CEILING)
    return (steps * BILL_RATE_STEP).quantize(Decimal("0.01"))


SHIPPING_LINE_CODE = "DO"  # charge master "Shipping Line Charges"
VALUE_NOTE = "Value calculated in the proforma is tentative, not as per the final bill, and can vary slightly."


def value_label(v: dict) -> str:
    """'Value of Goods (w shipping)' / '(w/o shipping)' — whether the shipping line is in it (client, 2026-09-30)."""
    return f"Value of Goods ({'w' if v.get('with_shipping') else 'w/o'} shipping)"


def value_summary(proforma: Proforma) -> dict[str, Optional[Decimal]]:
    """Template row 37-38: value of goods, GST input, value/kg, bill rate,
    GST output, GST difference (the GST Difference line itself is left out)."""
    s = proforma.shipment
    lines = [li for li in proforma.line_items if not _is_gst_difference(li)]
    value = Decimal(s.assessable_value or 0) + sum((Decimal(li.amount) for li in lines), ZERO)
    gst_input = sum((Decimal(li.gst_amount) for li in lines), ZERO)
    wt = weight_kgs(s)
    rate = Decimal(proforma.bill_rate) if proforma.bill_rate is not None else None
    output = (GST_OUTPUT_RATE * rate * wt).quantize(Decimal("0.01")) if rate is not None and wt else None
    return {
        "value_of_goods": value,
        "with_shipping": any(li.charge is not None and li.charge.code == SHIPPING_LINE_CODE for li in lines),
        "gst_input": gst_input,
        "value_per_kg": (value / wt).quantize(Decimal("0.01")) if wt else None,
        "suggested_bill_rate": suggest_bill_rate(value / wt if wt else None, gst_input, wt),
        "lowest_bill_rate": lowest_bill_rate(value / wt if wt else None, gst_input, wt),
        "manual_rate_ok": (bill_rate_allowed(rate, value / wt if wt else None, gst_input, wt)
                           if rate is not None else None),
        "bill_rate": rate,
        "gst_output": output,
        "gst_difference": max(ZERO, output - gst_input) if output is not None else None,
    }


def _be_field(shipment: Shipment, key: str) -> Optional[str]:
    """A field from the latest Assessed/OOC BE that was read."""
    be_docs = [d for d in shipment.documents
               if d.document_type in (DocumentType.OOC_BILL_OF_ENTRY, DocumentType.ASSESSED_BILL_OF_ENTRY)]
    for d in sorted(be_docs, key=lambda d: d.id, reverse=True):
        value = ((d.extraction or {}).get("fields") or {}).get(key)
        if value:
            return value
    return None


def documents_not_attached(shipment: Shipment) -> list[str]:
    """Documents the proforma is worked out from that aren't attached yet. Until they are,
    no proforma is generated — figures typed from memory are easy to miss or get wrong
    (client, 2026-10-03). The Assessed BE gives the duty, assessable value, importer and
    stamp duty; an OOC copy carries the same figures, so either one will do."""
    types = {d.document_type for d in shipment.documents}
    missing = []
    if not types & {DocumentType.ASSESSED_BILL_OF_ENTRY, DocumentType.OOC_BILL_OF_ENTRY}:
        missing.append("Assessed BE")
    return missing


def be_importer_name(shipment: Shipment) -> Optional[str]:
    """Importer as printed on the latest Assessed/OOC BE that was read."""
    return _be_field(shipment, "importer_name")


def be_ad_code(shipment: Shipment) -> Optional[str]:
    return _be_field(shipment, "ad_code")


def _first_name(name: Optional[str]) -> Optional[str]:
    """'Harekrishna Rubber Industries Pvt Ltd' -> 'Harekrishna'; 'MAHRISHI RECYCLERS' -> 'Mahrishi'."""
    word = re.sub(r"[^A-Za-z0-9&]", "", (name or "").split()[0]) if (name or "").split() else ""
    return word.title() if word else None


def copy_for(proforma: Proforma, db: Optional[Session] = None) -> Optional[str]:
    """HSS copies are marked by the party they're for, by first name ('For Harekrishna'
    / 'For Mahrishi') — client, 2026-09-28. Seller = BL consignee (AD-code org) or the
    tracker's HSS seller; buyer = the Bill To (BE importer)."""
    if not proforma.bill_to_role:
        return None
    s = proforma.shipment
    db = db or object_session(proforma)
    if proforma.bill_to_role == "seller":
        org = bl_consignee_organization(db, s)
        name = org.name if org else s.hss_seller
    else:
        org = bill_to_organization(proforma, db)
        name = org.name if org else bill_to_name(proforma)
    first = _first_name(name)
    return f"For {first}" if first else None


def invoice_filename(proforma: Proforma, ext: str) -> str:
    """Spec §5.5 pattern: '{Importer} - {MBL} - {BE No} - proforma'."""
    s = proforma.shipment
    parts = [bill_to_name(proforma) or "Client", s.mbl]
    if s.be_no:
        parts.append(s.be_no)
    who = copy_for(proforma)
    label = "proforma" + (f" (for {who[4:]})" if who else "")  # "... - proforma (for Harekrishna)"
    if proforma.version_number > 1:
        label += f" v{proforma.version_number}"
    name = " - ".join(p.strip() for p in parts + [label] if p)
    return re.sub(r'[\\/*?:"<>|]', "", name) + f".{ext}"


def _money(v) -> str:
    return str(Decimal(v).quantize(Decimal("0.01"))) if v is not None else None


def build_invoice(proforma: Proforma) -> dict[str, Any]:
    s: Shipment = proforma.shipment
    lines = sorted(proforma.line_items, key=lambda li: (li.sort_order, li.id))
    sections = []
    totals = {}
    for cat in ChargeCategory:
        if cat == ChargeCategory.COST_INCLUSION and not s.is_hss:
            continue  # cost inclusion (and the value of goods) only on HSS proformas (client, 2026-10-01)
        rows = [li for li in lines if li.category == cat]
        subtotal = sum((Decimal(li.total) for li in rows), ZERO)
        totals[cat] = subtotal
        sections.append({
            "category": cat.value,
            "title": SECTION_TITLES[cat],
            "lines": [{
                "id": li.id, "description": li.description, "sac_code": li.sac_code,
                "rate": _money(li.rate), "quantity": format(Decimal(li.quantity).normalize(), "f"),
                "amount": _money(li.amount), "gst_rate": format(Decimal(li.gst_rate).normalize(), "f"),
                "gst_amount": _money(li.gst_amount), "gst_is_actual": li.gst_is_actual, "is_manual": li.is_manual,
                "total": _money(li.total),
            } for li in rows],
            "subtotal": _money(subtotal),
            "amount_subtotal": _money(sum((Decimal(li.amount) for li in rows), ZERO)),  # before tax
            "gst_subtotal": _money(sum((Decimal(li.gst_amount) for li in rows), ZERO)),
            "counts_in_total": cat != ChargeCategory.COST_INCLUSION,
        })
    grand = sum((v for cat, v in totals.items() if cat != ChargeCategory.COST_INCLUSION), ZERO)
    wt = weight_kgs(s)
    db = object_session(proforma)
    org = bill_to_organization(proforma, db)
    name = (org.name if org else None) or bill_to_name(proforma)
    consignee_org = bl_consignee_organization(db, s)
    bl_consignee = consignee_org.name if consignee_org else s.consignee
    # Seller copy of an HSS invoice: the seller (BL consignee) pays the buyer (BE importer)
    # who pays whom on this invoice (every HSS shipment): seller invoice "<seller> pays
    # <buyer>", buyer invoice "<buyer> pays Clarus"; otherwise "<importer> pays Clarus"
    seller = (consignee_org.name if consignee_org else s.hss_seller) if s.is_hss else None
    if proforma.bill_to_role == "seller" and seller:
        payer_chain = [seller, name or s.hss_buyer]
    else:
        payer_chain = [name or s.consignee, company_details()["name"]]
    grand_total_label = " pays ".join(x for x in payer_chain if x)
    disclaimer = None
    if proforma.bill_to_role == "seller":
        disclaimer = f"{seller or 'Seller'} to pay {name or s.hss_buyer or 'Buyer'}"
    challan = latest_challan(db, s.be_no, s.be_dt)
    duty = customs_duty(s, challan)
    value = value_summary(proforma)
    return {
        "company": company_details(),
        "title": "PROFORMA INVOICE",
        "not_attached": documents_not_attached(s),  # downloads stay off until these are attached
        "copy_label": copy_for(proforma, db),
        "disclaimer": disclaimer,
        "bill_to": {
            "name": name,
            "party": bill_to_name(proforma),
            "organization": {
                "id": org.id, "name": org.name, "address": org.address, "state": org.state,
                "gstin": org.gstin, "pan": org.pan, "iec": org.iec, "email": org.email, "phone": org.phone,
            } if org else None,
            "bl_consignee": bl_consignee,
            "bl_consignee_ad_code": be_ad_code(s),
            "be_importer": be_importer_name(s),
            "hss": {"seller": s.hss_seller, "buyer": s.hss_buyer} if s.is_hss else None,
        },
        "details": {
            "invoice_date": (proforma.created_at.date() if proforma.created_at else date.today()).isoformat(),
            "be_no": s.be_no, "be_date": s.be_dt.isoformat() if s.be_dt else None, "port": s.port,
            "job": s.job, "version": proforma.version_number, "name": proforma.name, "status": proforma.status.value,
        },
        "reference": {
            "assessable_value": _money(s.assessable_value), "mbl": s.mbl, "hbl": s.hbl,
            "hss": f"{s.hss_seller} → {s.hss_buyer}" if s.is_hss else "N/A",
            "containers": container_count(s), "weight_kgs": str(wt) if wt is not None else None,
            "exam_applicable": "YES" if s.under_examination else "NO",
        },
        "sections": sections,
        "is_hss": bool(s.is_hss),
        "customs_duty": {
            "interest": _money(duty["interest"]), "total": _money(duty["total"]), "source": duty["source"],
            "challan_uploaded_at": challan.as_of.isoformat() if challan else None,
            "challan_today": bool(challan and ist_day(challan.as_of) == today_ist()),
        } if duty else None,
        "value": {**{k: (v if isinstance(v, bool) else _money(v)) for k, v in value.items()},
                  "label": value_label(value), "note": VALUE_NOTE,
                  "bill_rate_manual": bool(proforma.bill_rate_manual)} if s.is_hss else None,
        "grand_total": _money(round_off(grand)[0]),
        "round_off": _money(round_off(grand)[1]),  # + / − paise to the rupee
        "grand_total_label": grand_total_label,
        "notes": proforma_notes(),
        "bank": company_bank(),
    }

"""
Fill a proforma from what the shipment knows — and keep DRAFT proformas in step
automatically when documents, the duty challan or the paid-by-us switches change.

Two modes:
  full (the "Fill / refresh from shipment" button): adds Agency, Examination,
      Royalty and everything document-derived; clears remembered removals.
  auto (after any change): only the derived lines — Customs Duty, Stamp Duty,
      CFS, Shipping Line, and Examination (while the shipment is under
      examination) — are added / updated / removed.
Never touched automatically: a line someone edited by hand (is_manual) and a
derived line someone removed (remembered in Proforma.suppressed).

Shipping line: ONE line with the total of the selected charges of all counted
liner invoices, SAC column "Liner Inv" (client, 2026-09-28) — Cost Inclusion, or
Reimbursement when the line is paid by us.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.challan import ist_day, today_ist
from app.core.enums import ChargeCategory, ProformaStatus
from app.extraction.cfs_totals import cost_inclusion, invoice_charges, line_invoices_counted
from app.invoice.build import SECTION_TITLES, _norm, value_summary, be_importer_name, bl_consignee_organization, customs_duty, latest_challan, ooc_duty, match_organization, stamp_duty, weight_kgs
from app.invoice.lines import container_count, new_line, recalc, sync_gst_difference
from app.models.charge import ChargeMasterEntry
from app.models.document import ShipmentDocument
from app.models.licence import Licence
from app.models.pricing_rule import PricingRule
from app.models.proforma import Proforma, ProformaLineItem
from app.models.shipment import Shipment

# kept up to date automatically: read from documents, or (EC) follows "under examination"
DERIVED_CODES = {"CD", "SD", "CFS", "DO", "EC"}
LINE_CODE = "DO"  # charge master "Shipping Line Charges"
LINE_SAC = "Liner Inv"  # SAC column for the shipping line total: as per the liner's invoice
ZERO = Decimal("0")


def line_key(li: ProformaLineItem) -> str:
    """Identity of a derived line: shipping line lines are one per SAC."""
    code = li.charge.code if li.charge else "?"
    return f"{code}:{li.sac_code}" if code == LINE_CODE else code


def line_excluded_by(db: Session, s: Shipment) -> Optional[str]:
    """Why the shipping line stays out of the cost inclusion, or None if it goes in.
    The shipment's own switch wins; on auto, any party on the shipment (BE importer,
    consignee, HSS seller / buyer) whose organisation says "not in cost inclusion"."""
    if s.line_cost_inclusion == "include":
        return None
    if s.line_cost_inclusion == "exclude":
        return "switched off for this shipment"
    return client_line_excluded_by(db, s)


def client_line_excluded_by(db: Session, s: Shipment) -> Optional[str]:
    """The client default, whatever the shipment's own switch says: "<org>'s setting" if a party on the
    shipment keeps the line out of the cost inclusion, else None (it goes in)."""
    for name in {be_importer_name(s), s.consignee, s.hss_seller, s.hss_buyer} - {None, ""}:
        org = match_organization(db, name)
        if org is not None and not org.line_in_cost_inclusion:
            return f"{org.name}'s setting"
    return None


def shipping_line_groups(db: Session, s: Shipment) -> list[dict]:
    """Cost inclusion of the counted shipping line invoices, grouped by the SAC on
    the liner's invoice: [{sac, amount, gst, names, carriers}]."""
    docs = line_invoices_counted(db.query(ShipmentDocument).filter(ShipmentDocument.shipment_id == s.id).all())
    groups: "OrderedDict[Optional[str], dict]" = OrderedDict()

    def put(sac, amount, gst, name, carrier):
        g = groups.setdefault(sac, {"sac": sac, "amount": ZERO, "gst": ZERO, "names": [], "carriers": []})
        g["amount"] += amount
        g["gst"] += gst
        if name and name not in g["names"]:
            g["names"].append(name)
        if carrier and carrier not in g["carriers"]:
            g["carriers"].append(carrier)

    for d in docs:
        before, gst = cost_inclusion(d)
        if before is None:
            continue
        before, gst = Decimal(before), Decimal(gst or 0)
        carrier = ((d.extraction or {}).get("fields") or {}).get("carrier")
        excluded = set(d.cost_excluded or [])
        kept = [] if d.cost_manual else [c for i, c in enumerate(invoice_charges(d)) if i not in excluded]
        if not kept:
            put(None, before, gst, None, carrier)
            continue
        known = all(c.get("gst") is not None for c in kept)
        spent = ZERO
        for i, c in enumerate(kept):
            amount = Decimal(str(c["amount"] or 0))
            if known:
                share = Decimal(str(c["gst"]))
            elif i == len(kept) - 1:
                share = gst - spent  # remainder, so the lines add up to the invoice's GST
            else:
                share = (gst * amount / before).quantize(Decimal("0.01")) if before else ZERO
            spent += share
            put(c.get("sac"), amount, share, c.get("description"), carrier)
    return list(groups.values())


def _same(a: str, b: str) -> bool:
    """Loose name match: equal, or one is the start of the other ('HKR' / 'HKR RUBBER')."""
    return a == b or (a + " ").startswith(b + " ") or (b + " ").startswith(a + " ")


def _seller_names(db: Session, s: Shipment) -> set[str]:
    """HSS seller as the tracker writes it and as registered (org holding the BE's AD code)."""
    if not s.is_hss:
        return set()
    consignee = bl_consignee_organization(db, s)
    return {_norm(x) for x in (s.hss_seller, consignee.name if consignee else None) if x}


def licence_rates_for(db: Session, s: Shipment) -> tuple[Optional[Licence], dict[str, dict], Optional[str]]:
    """(licence, {charge code: rate row}, note). Per charge, the most specific row
    for this shipment wins: seller + port > seller > port > neither. Rates follow
    the HSS seller on HSS shipments."""
    number = (s.license or "").strip()
    if not number or number == "-":
        return None, {}, None
    lic = db.query(Licence).filter(Licence.number == number).first()
    if lic is None:
        return None, {}, f"Licence {number}: no rates set up yet — standard rates used (Rates page → Licences)"
    if not lic.is_active:
        return None, {}, f"Licence {number} is closed — standard rates used"
    sellers = _seller_names(db, s)
    best: dict[str, tuple[int, dict]] = {}
    for row in lic.rates or []:
        seller, port = row.get("seller"), row.get("port")
        if port and port != s.port:
            continue
        if seller and not any(_same(_norm(seller), x) for x in sellers):
            continue
        score = (2 if seller else 0) + (1 if port else 0)
        if row.get("code") and (row["code"] not in best or score > best[row["code"]][0]):
            best[row["code"]] = (score, row)
    return lic, {code: row for code, (_, row) in best.items()}, None


def pricing_rule_for(db: Session, proforma: Proforma) -> Optional[PricingRule]:
    """HSS pricing rule for this copy (seller / buyer): buyer = the BE importer; seller =
    the rule's seller if it names one (matched against the BL consignee's registered
    name and the tracker's HSS seller). A rule naming the seller wins over "any seller"."""
    s = proforma.shipment
    if not s.is_hss or not proforma.bill_to_role:
        return None
    buyer = _norm(be_importer_name(s) or proforma.bill_to)
    if not buyer:
        return None
    sellers = _seller_names(db, s)
    same = _same
    best = None
    for rule in db.query(PricingRule).filter(PricingRule.is_active.is_(True),
                                             PricingRule.bill_to_role == proforma.bill_to_role):
        if not same(_norm(rule.importer_name), buyer):
            continue
        if rule.seller_name:
            if any(same(_norm(rule.seller_name), x) for x in sellers):
                return rule  # exact pair
        elif best is None:
            best = rule
    return best


def sync_proforma(db: Session, proforma: Proforma, full: bool) -> tuple[list[str], list[str], list[str]]:
    """Returns (added, updated, skipped) — human-readable, for the Fill result."""
    s = proforma.shipment
    charges = {c.code: c for c in db.query(ChargeMasterEntry).filter(ChargeMasterEntry.is_active.is_(True))}
    added, updated, skipped = [], [], []
    importer = be_importer_name(s)  # Bill To is always the BE importer — keep the stored name in step
    if importer and proforma.bill_to != importer:
        proforma.bill_to = importer
    if full:
        proforma.suppressed = None
    suppressed = set(proforma.suppressed or [])
    wanted_keys: set[str] = set()

    def find(key: str) -> Optional[ProformaLineItem]:
        return next((li for li in proforma.line_items if line_key(li) == key), None)

    def add(code, rate, qty=Decimal("1"), gst=None, description=None, category=None, sac=None):
        charge = charges.get(code)
        if charge is None:
            skipped.append(f"{code}: not in the charge master")
            return
        key = f"{code}:{sac or charge.sac_code}" if code == LINE_CODE else code
        wanted_keys.add(key)
        derived = code in DERIVED_CODES
        existing = find(key)
        if existing is not None:
            if existing.is_manual and code == "CD" and ooc_duty(s) is not None:
                existing.is_manual = False  # Customs Duty follows the OOC copy, never a hand figure
            if existing.is_manual:
                if full:
                    skipped.append(f"{existing.description}: edited by hand — left as is")
                return
            if not derived:
                if full:
                    skipped.append(f"{charge.name}: already on this proforma")
                return
            before = (Decimal(existing.total), existing.description, existing.category)
            existing.rate, existing.quantity = Decimal(rate), Decimal(qty)
            if description:
                existing.description = description
            if category:
                existing.category = category
            if gst is None:
                existing.gst_is_actual = False
            recalc(existing, gst)
            if (Decimal(existing.total), existing.description, existing.category) != before:
                updated.append(f"{existing.description} → ₹{Decimal(existing.total):,.2f}")
            return
        if not full and (not derived or key in suppressed):
            return
        li = new_line(proforma, charge, Decimal(rate), Decimal(qty), description, category, gst, sac_code=sac)
        db.add(li)
        proforma.line_items.append(li)
        added.append((description or charge.name) + (f" ({SECTION_TITLES[category]})" if category else ""))

    n, wt = container_count(s), weight_kgs(s)

    def add_formula(code: str, row: dict, source: str) -> None:
        """₹/container x containers + ₹/kg x weight + flat, shown as rate x qty when it's one part."""
        per_c, per_kg, flat = (Decimal(str(row.get(k) or 0)) for k in ("per_container", "per_kg", "flat"))
        if per_c and n is None:
            skipped.append(f"{code}: {source} needs the container count")
            return
        if per_kg and wt is None:
            skipped.append(f"{code}: {source} needs the gross weight")
            return
        category = ChargeCategory(row["category"]) if row.get("category") else None
        parts = [p for p in (per_c, per_kg, flat) if p]
        if len(parts) <= 1 and per_c:
            add(code, per_c, n, category=category)
        elif len(parts) <= 1 and per_kg:
            add(code, per_kg, wt, category=category)
        else:
            add(code, per_c * (n or 0) + per_kg * (wt or 0) + flat, category=category)

    licence, lic_rates, lic_note = licence_rates_for(db, s)
    if lic_note and full:
        skipped.append(lic_note)
    rule = pricing_rule_for(db, proforma) if full else None
    rule_codes = {ln.get("code") for ln in (rule.lines or [])} if rule else set()

    # Agency (button) and Examination (while under examination): the licence's rate, else the standard rate
    for code, wanted in (("AC", full), ("EC", bool(s.under_examination))):
        c = charges.get(code)
        if not wanted or c is None:
            continue
        if code in lic_rates:
            add_formula(code, lic_rates[code], f"licence {licence.number}")
        elif licence is not None and code == "EC":
            skipped.append(f"Examination: licence {licence.number} has no rate for {s.port or 'this port'} — "
                           "set it on the Rates page or add it by hand")
        elif n is None:
            skipped.append(f"{c.name}: shipment has no container count")
        elif c.default_rate is None:
            skipped.append(f"{c.name}: no default rate in the charge master — add it by hand")
        else:
            add(code, c.default_rate, n, category=ChargeCategory.SERVICE)

    # the licence's other charges (Bond, Documentation, Other…); an HSS rule's lines take precedence
    if full:
        for code, row in lic_rates.items():
            if code not in ("AC", "EC") and code not in rule_codes:
                add_formula(code, row, f"licence {licence.number}")

    challan = latest_challan(db, s.be_no, s.be_dt)
    duty = customs_duty(s, challan)
    duty_total = None
    if duty is not None:
        desc = "Customs Duty" + (f" (incl. interest ₹{duty['interest']:,.2f})" if duty["interest"] else "")
        add("CD", duty["basic"], gst=duty["gst"], description=desc)
        duty_total = duty["total"]
        if duty["source"] == "ooc":
            skipped.append("Customs Duty: the OOC copy's total (final amount paid) — fixed, can't be edited")
        elif challan is None:
            skipped.append("ACTION NEEDED — upload the duty challan (Dashboard) for this BE: without it or an OOC copy "
                           "the interest is unknown and Customs Duty is the BE amount only")
        elif ist_day(challan.as_of) != today_ist():
            skipped.append(f"Interest: latest challan list is from {ist_day(challan.as_of):%d-%m-%Y} — upload today's for current interest")
    else:
        skipped.append("Customs Duty: no duty amount yet (upload the Assessed / OOC BE or the duty challan)")

    sd = stamp_duty(s, duty_total)
    if sd is None:
        skipped.append("Stamp Duty: needs the assessable value and the port")
    elif sd == 0:
        skipped.append(f"Stamp Duty: none at {s.port} (only Mundra / Nhava Sheva so far)")
    else:
        add("SD", sd, gst=ZERO)

    if s.cfs_paid_by_us:
        if s.cfs_amount_before_tax is not None:
            if s.cfs_billed_as == "taxable":  # Billed by Clarus: our 18% GST on the CFS basic
                add("CFS", Decimal(s.cfs_amount_before_tax), category=ChargeCategory.SERVICE)
            else:  # reimbursement at actuals: the CFS invoice's own GST
                add("CFS", Decimal(s.cfs_amount_before_tax), gst=Decimal(s.cfs_gst_amount or 0),
                    category=ChargeCategory.REIMBURSEMENT)
        else:
            skipped.append("CFS: no CFS invoice amounts yet")
    else:
        skipped.append("CFS: not paid by us — invoice only")

    if rule is not None:
        for line in rule.lines or []:
            add_formula(line.get("code"), line, rule.name)
    elif full and s.is_hss:
        roy = charges.get("ROY")
        if roy is not None and wt is not None and roy.default_rate is not None:
            add("ROY", roy.default_rate, wt)
        elif roy is not None:
            skipped.append("Royalty: needs the gross weight (and a default rate per kg)")

    # the client normally pays the line directly -> Cost Inclusion; paid by us -> Reimbursement
    line_cat = ChargeCategory.REIMBURSEMENT if s.line_paid_by_us else ChargeCategory.COST_INCLUSION
    groups = shipping_line_groups(db, s)
    excluded_by = None if s.line_paid_by_us else line_excluded_by(db, s)
    if groups and line_cat == ChargeCategory.COST_INCLUSION and not s.is_hss:
        skipped.append("Shipping line: cost inclusion is only for HSS shipments")
    elif groups and excluded_by:
        skipped.append(f"Shipping line: not in cost inclusion ({excluded_by}) — switch it on for this shipment to add it")
    elif groups:  # one total of the selected charges
        carriers = sorted({c for g in groups for c in g["carriers"]})
        add(LINE_CODE, sum((g["amount"] for g in groups), ZERO), gst=sum((g["gst"] for g in groups), ZERO),
            description="Shipping Line" + (f" ({', '.join(carriers)})" if carriers else " (destination charges)"),
            category=line_cat, sac=LINE_SAC)
    else:
        skipped.append("Shipping line: no destination charges invoice yet")

    # derived lines whose source is gone (e.g. CFS switched to "not paid by us", an invoice removed)
    for li in list(proforma.line_items):
        code = li.charge.code if li.charge else None
        if code in ("CFS", LINE_CODE, "EC") and not li.is_manual and line_key(li) not in wanted_keys:
            proforma.line_items.remove(li)
            db.delete(li)
            updated.append(f"{li.description}: removed (no longer applies)")

    # HSS: the bill rate follows the rules (sync_gst_difference -> sync_bill_rate)
    if full and s.is_hss and proforma.bill_rate is None and not proforma.bill_rate_manual \
            and value_summary(proforma)["suggested_bill_rate"] is not None:
        added.append(f"Bill rate ₹{value_summary(proforma)['suggested_bill_rate']}/kg (by the rules — follows the costs)")
    sync_gst_difference(db, proforma)
    return added, updated, skipped


def restore_line(db: Session, proforma: Proforma, key: str) -> bool:
    """Un-remove a derived line (or add one by charge code) and fill it from the
    documents. Returns False when the documents have nothing for it."""
    code = key.split(":")[0]
    if code not in DERIVED_CODES:
        return False
    proforma.suppressed = sorted(k for k in (proforma.suppressed or []) if k.split(":")[0] != code) or None
    sync_proforma(db, proforma, full=False)
    return any(line_key(li).split(":")[0] == code for li in proforma.line_items)


def refresh_draft_proformas(db: Session, shipment: Shipment) -> None:
    """After a document / challan / shipment change: bring every DRAFT proforma
    of the shipment up to date (derived lines only). Caller commits."""
    db.flush()
    db.expire(shipment, ["documents", "proformas"])
    for p in shipment.proformas:
        if p.status == ProformaStatus.DRAFT:
            sync_proforma(db, p, full=False)

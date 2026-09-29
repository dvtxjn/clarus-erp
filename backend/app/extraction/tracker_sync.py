"""
Document upload -> shipment updates (spec §3.3).

Two layers:
1. Fields read from the PDF (see document_extract.py) fill in the shipment:
   - identifiers (BE no, BE date, port, MBL, HBL, containers, gross wt) are
     only filled when the shipment's value is blank — a PDF never silently
     overwrites an identifier someone typed; a mismatch is reported instead
     (BE no / BL no are the most important keys, so they're checked first).
   - amounts (assessable value, IGST, duty; CFS amounts) always take the
     latest document's figures.
2. The document type itself sets flags/status:
   - Assessed BE -> status at least BE Assessed
   - OOC BE      -> OOC = yes, Duty Paid = yes (OOC isn't granted before duty
                    is paid), OOC date, examination yes/no, status OOC Done
   - CFS tax invoice -> CFS Inv = yes
   - DO letter   -> DO = yes
   - Gatepass BE -> status Cleared + Cleared Date (moves to the Cleared tab)
Status only ever moves forward here, never back.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

import re

from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.status_rules import EVIDENCE_FIELDS, status_after_evidence_change
from app.core.enums import DocumentType, ShipmentStatus
from app.extraction.cfs_totals import default_cost_inclusion, invoice_charges, recompute_invoice_totals
from app.extraction.document_extract import BE_TYPES, CFS_TYPES, INVOICE_TYPES, LINE_TYPES, RECEIPT_TYPES, parse_ddmmyyyy
from app.models.document import ShipmentDocument
from app.models.shipment import Shipment

PIPELINE = list(ShipmentStatus)

FIELD_LABELS = {
    "be_no": "BE No", "be_dt": "BE Date", "port": "Port", "mbl": "MBL", "hbl": "HBL",
    "container": "Containers", "gross_wt": "Gross Wt", "assessable_value": "Assessable value",
    "igst_amount": "IGST", "duty_amount": "Duty amount", "cfs_amount_before_tax": "CFS amount (before tax)",
    "cfs_gst_amount": "CFS GST", "cfs_amount_total": "CFS amount (total)",
    "line_amount_before_tax": "Shipping line (before tax)", "line_gst_amount": "Shipping line GST",
    "line_amount_total": "Shipping line (total)", "ooc": "OOC", "duty_paid": "Duty Paid",
    "ooc_date": "OOC date", "under_examination": "Under examination", "examination_at": "Examination date/time",
    "cfs_inv_received": "CFS Inv", "line_paid": "Line Paid", "do": "DO", "status": "Status", "cleared_date": "Cleared Date",
}


def kg_to_mts(kg: Any) -> Optional[str]:
    try:
        if kg in (None, ""):
            return None
        mts = (Decimal(str(kg)) / 1000).quantize(Decimal("0.001"), ROUND_HALF_UP)
        return f"{mts} MTS"
    except InvalidOperation:
        return None


def _money(v: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except InvalidOperation:
        return None


class _Sync:
    def __init__(self, db: Session, shipment: Shipment, user_id: Optional[int]):
        self.db, self.s, self.user_id = db, shipment, user_id
        self.updated: list[str] = []
        self.notes: list[str] = []

    def set(self, field: str, value: Any) -> None:
        old = getattr(self.s, field)
        if value is None or old == value:
            return
        record_change(self.db, "shipments", self.s.id, field, old, value, self.user_id)
        setattr(self.s, field, value)
        self.updated.append(field)

    def fill(self, field: str, value: Any, report: bool = True) -> None:
        """Only fill a blank; report (don't overwrite) a different existing value.
        A value that's part of the tracker's value counts as a match (the MBL cell
        often holds 'MBL/HBL')."""
        if value in (None, ""):
            return
        old = getattr(self.s, field)
        if old in (None, ""):
            self.set(field, value)
            return
        norm = lambda v: re.sub(r"\s+", "", str(v)).upper()  # noqa: E731
        if report and norm(value) not in norm(old):
            self.notes.append(f"{FIELD_LABELS[field]} on the document ({value}) differs from the tracker ({old}) — not changed.")

    def advance(self, status: ShipmentStatus) -> None:
        if PIPELINE.index(status) > PIPELINE.index(self.s.status):
            self.set("status", status)


def _shipping_line_checks(sync: "_Sync", shipment: Shipment, document: ShipmentDocument, fields: dict) -> None:
    """BL on the invoice vs the tracker; which charges are cost inclusion."""
    bl = (fields.get("bl_no") or "").upper()
    ours = re.sub(r"\s+", "", f"{shipment.mbl or ''}/{shipment.hbl or ''}").upper()
    if bl and bl not in ours:
        sync.notes.append(f"BL on the shipping line invoice ({bl}) differs from the tracker ({shipment.mbl}).")
    document.extraction = {**(document.extraction or {}), "fields": fields}
    default_cost_inclusion(document)
    charges = invoice_charges(document)
    if fields.get("charges") and not charges:
        sync.notes.append("The charge lines read don't add up to the invoice's base amount — the whole invoice is "
                          "counted as cost inclusion; adjust it on the Overview if needed.")
    left_out = [c for c in charges if c.get("in_cost_inclusion") is False]
    if left_out:
        desc = ", ".join(f"{c['description']} ({c['currency']} → ₹{c['amount']:,.2f})" for c in left_out)
        sync.notes.append(f"Left out of cost inclusion (not INR / freight head): {desc}. Tick it back on the Overview if it counts.")
    review = [c["description"] for c in charges if c.get("review")]
    if review:
        sync.notes.append(f"Please check: {', '.join(review)} — billed in INR but named like freight, so left out.")


def apply_tracker_sync(db: Session, shipment: Shipment, document: ShipmentDocument,
                       changed_by_id: Optional[int], fields: Optional[dict] = None) -> dict:
    """Mutates `shipment`; caller commits. Returns {"updated": [...labels], "notes": [...]}."""
    if document.tracker_sync_applied:
        return {"updated": [], "notes": []}
    fields = fields or {}
    sync = _Sync(db, shipment, changed_by_id)
    t = document.document_type

    if fields.get("error"):
        sync.notes.append(fields["error"])

    if t in BE_TYPES and not fields.get("error"):
        sync.fill("be_no", fields.get("be_no"))
        sync.fill("be_dt", parse_ddmmyyyy(fields.get("be_date")))
        sync.fill("mbl", fields.get("mawb"))
        hawb = fields.get("hawb")
        if hawb and hawb.replace(" ", "").upper() not in (shipment.mbl or "").replace(" ", "").upper():
            sync.fill("hbl", hawb)  # HBL is usually typed into the MBL cell after a slash
        sync.fill("port", fields.get("port_code"))
        if fields.get("cont_count") not in (None, "0"):
            sync.fill("container", fields.get("cont_count"), report=False)
        # The BE's gross weight is always taken as correct. It's printed in KGS;
        # the tracker keeps the sheet's format, e.g. 84885 -> "84.885 MTS".
        sync.set("gross_wt", kg_to_mts(fields.get("gross_wt")))
        sync.set("assessable_value", _money(fields.get("tot_ass_val")))
        sync.set("igst_amount", _money(fields.get("igst")))
        sync.set("duty_amount", _money(fields.get("tot_amount")))
        # Client rule (2026-09-29): customs duty always carries IGST — none found = a problem to check
        if fields.get("tot_amount") and not _money(fields.get("igst")):
            fields["gst_missing"] = True
            sync.notes.append("IGST not found on this Bill of Entry — duty always includes IGST; check the figures "
                              "(scan or unusual layout?).")
        if not fields.get("be_no"):
            sync.notes.append("Couldn't find the BE number on this document — please check it's the right file.")

    if t in INVOICE_TYPES and not fields.get("error"):
        what = "CFS invoice" if t in CFS_TYPES else "shipping line invoice"
        if fields.get("be_no") and shipment.be_no and fields["be_no"] != shipment.be_no:
            sync.notes.append(f"BE No on the {what} ({fields['be_no']}) differs from the tracker ({shipment.be_no}).")
        if not document.amounts_edited:  # never overwrite figures someone corrected by hand
            before, gst = _money(fields.get("cfs_before_tax")), _money(fields.get("cfs_gst"))
            total = _money(fields.get("cfs_after_tax"))
            document.amount_before_tax, document.gst_amount = before, gst
            document.amount_total = before + gst if before is not None and gst is not None else total
        if t in LINE_TYPES:
            _shipping_line_checks(sync, shipment, document, fields)
        totals = ("cfs_amount_before_tax", "cfs_gst_amount", "cfs_amount_total",
                  "line_amount_before_tax", "line_gst_amount", "line_amount_total")
        before_totals = {f: getattr(shipment, f) for f in totals}
        recompute_invoice_totals(db, shipment, changed_by_id)
        sync.updated += [f for f in totals if getattr(shipment, f) != before_totals[f]]
        if all(fields.get(k) is None for k in ("cfs_before_tax", "cfs_gst", "cfs_after_tax")):
            sync.notes.append(f"Couldn't read any amounts from this {what} — it may be a scan or an "
                              "unfamiliar layout. Enter the amounts by hand (Overview → Edit) or send us a sample.")
        # Client rule (2026-09-29): every CFS / shipping line invoice has GST — none found = a problem
        if (fields.get("cfs_before_tax") or fields.get("cfs_after_tax")) and not _money(fields.get("cfs_gst")):
            fields["gst_missing"] = True
            sync.notes.append(f"GST not found on this {what} — these invoices always have GST; check the figures "
                              "(scan, wrong document, or a layout we don't read yet).")
        if fields.get("cfs_sanity_ok") is False:
            sync.notes.append(f"The {what} amounts don't add up (before tax + GST ≠ total) — please check the figures.")

    if t in RECEIPT_TYPES and not fields.get("error"):
        what = "CFS" if t == DocumentType.CFS_RECEIPT else "shipping line"
        if not document.amounts_edited:
            paid = _money(fields.get("amount_paid"))
            document.amount_before_tax, document.gst_amount, document.amount_total = paid, None, paid
        if fields.get("amount_paid") is None:
            sync.notes.append(f"Couldn't read the amount paid from this {what} receipt — enter it on the Overview "
                              "(or send us a sample so it reads next time).")
        if fields.get("be_no") and shipment.be_no and fields["be_no"] != shipment.be_no:
            sync.notes.append(f"BE No on the {what} receipt ({fields['be_no']}) differs from the tracker ({shipment.be_no}).")
    if t == DocumentType.SHIPPING_LINE_RECEIPT:
        sync.set("line_paid", True)  # the line has been paid

    if t == DocumentType.ASSESSED_BILL_OF_ENTRY:
        sync.advance(ShipmentStatus.BE_ASSESSED)
    elif t == DocumentType.OOC_BILL_OF_ENTRY and fields.get("is_ooc_copy") is False:
        sync.notes.append("This doesn't look like an OOC copy (no 'OOC COPY' marking on it) — "
                          "OOC was not ticked. Check the file, or tick OOC by hand.")
    elif t == DocumentType.OOC_BILL_OF_ENTRY:
        sync.set("ooc", True)
        sync.set("duty_paid", True)
        sync.set("ooc_date", parse_ddmmyyyy(fields.get("ooc_date")))
        if not fields.get("error"):
            if fields.get("under_examination") is not None:
                sync.set("under_examination", fields["under_examination"])
            else:
                sync.notes.append("Couldn't find the Processing Details table — examination not read.")
            sync.set("examination_at", fields.get("examination_at"))
        sync.advance(ShipmentStatus.OOC_DONE)
    elif t == DocumentType.CFS_TAX_INVOICE:
        sync.set("cfs_inv_received", True)
    elif t in (DocumentType.DO_LETTER, DocumentType.DO_EMPTY_LETTER):
        sync.set("do", True)
    elif t == DocumentType.GATEPASS_BILL_OF_ENTRY:
        sync.advance(ShipmentStatus.CLEARED)
        if shipment.cleared_date is None:
            sync.set("cleared_date", date.today())

    # Any evidence the document filled in (BE no, duty amount, OOC...) moves the status on
    if any(f in EVIDENCE_FIELDS for f in sync.updated):
        new_status = status_after_evidence_change(shipment)
        if new_status is not None:
            sync.advance(new_status)

    document.tracker_sync_applied = True
    return {"updated": [FIELD_LABELS.get(f, f) for f in sync.updated], "notes": sync.notes}

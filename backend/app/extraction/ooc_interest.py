"""One-off backfill (client, 2026-10-09): OOC copies read before v1.7.2 have no interest — read just the
'15.INT' figure from each and fix the shipment's duty without interest. Nothing else on the shipment is
re-applied, so hand corrections stay. Safe to run again: a copy already checked is skipped."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app import storage
from app.core.audit import record_change
from app.core.enums import DocumentType
from app.extraction.be_pdf import scan_be_pdf
from app.invoice.autofill import refresh_draft_proformas
from app.models.document import ShipmentDocument


def _dec(v) -> Optional[Decimal]:
    try:
        return Decimal(str(v).replace(",", "")) if v not in (None, "") else None
    except InvalidOperation:
        return None


def backfill_ooc_interest(db: Session, user_id: Optional[int]) -> dict:
    checked = with_interest = fixed = failed = 0
    docs = (db.query(ShipmentDocument).filter(ShipmentDocument.document_type == DocumentType.OOC_BILL_OF_ENTRY)
            .order_by(ShipmentDocument.id).all())
    for doc in docs:
        ext = doc.extraction or {}
        fields = ext.get("fields") or {}
        if "interest" in fields:
            continue  # already read with the INT column
        try:
            found = scan_be_pdf(storage.local_path(doc))
        except Exception:  # file gone / Drive unreachable: leave it for next time
            failed += 1
            continue
        if found.get("error"):
            failed += 1
            continue
        checked += 1
        interest = found.get("interest")
        doc.extraction = {**ext, "fields": {**fields, "interest": interest}}
        intr, total = _dec(interest), _dec(fields.get("tot_amount"))
        s = doc.shipment
        if intr and total is not None:
            with_interest += 1
            # only when the duty is still the OOC total as read (not corrected by hand)
            if s is not None and s.duty_amount is not None and Decimal(s.duty_amount) == total:
                record_change(db, "shipments", s.id, "duty_amount", s.duty_amount, total - intr, user_id)
                s.duty_amount = total - intr
                fixed += 1
        if s is not None:
            refresh_draft_proformas(db, s)
        db.commit()
    return {"checked": checked, "with_interest": with_interest, "duty_fixed": fixed, "failed": failed}

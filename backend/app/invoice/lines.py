"""Proforma line arithmetic shared by the API and the automatic refresh."""
from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.enums import ChargeCategory
from app.invoice.build import CEILING_CODES, GST_DIFFERENCE_CODE, value_summary
from app.models.charge import ChargeMasterEntry
from app.models.proforma import Proforma, ProformaLineItem


def new_line(proforma: Proforma, charge: ChargeMasterEntry, rate: Decimal, quantity: Decimal,
             description: Optional[str] = None, category: Optional[ChargeCategory] = None,
             gst_amount: Optional[Decimal] = None, total_override: Optional[Decimal] = None,
             sac_code: Optional[str] = None) -> ProformaLineItem:
    li = ProformaLineItem(
        proforma_id=proforma.id,
        charge_master_id=charge.id,
        charge=charge,
        description=description or charge.name,
        rate=rate,
        quantity=quantity,
        sac_code=sac_code or charge.sac_code,
        gst_rate=charge.gst_rate,
        category=category or charge.category,
        gst_is_actual=gst_amount is not None,
        sort_order=max((x.sort_order for x in proforma.line_items), default=0) + 1,
    )
    recalc(li, gst_amount, total_override)
    return li


def recalc(li: ProformaLineItem, gst_amount: Optional[Decimal] = None,
           total_override: Optional[Decimal] = None) -> None:
    """amount = rate x qty; GST = the actual figure if given, else gst_rate x amount.
    CFS and Royalty totals are rounded up to the rupee, like the template."""
    li.amount = (Decimal(li.rate) * Decimal(li.quantity)).quantize(Decimal("0.01"))
    if gst_amount is not None:
        li.gst_amount, li.gst_is_actual = Decimal(gst_amount).quantize(Decimal("0.01")), True
    elif not li.gst_is_actual:
        li.gst_amount = (li.amount * Decimal(li.gst_rate) / Decimal("100")).quantize(Decimal("0.01"))
    total = li.amount + Decimal(li.gst_amount)
    if li.charge is not None and li.charge.code in CEILING_CODES:
        total = Decimal(math.ceil(total))
    li.total = total_override if total_override is not None else total


def sync_gst_difference(db: Session, proforma: Proforma) -> None:
    """Keep the automatic GST Difference line in step: present (= max(0, GST
    output - GST input)) while a bill rate is set, gone when it isn't."""
    existing = [li for li in proforma.line_items if li.charge and li.charge.code == GST_DIFFERENCE_CODE]
    diff = value_summary(proforma)["gst_difference"] if proforma.bill_rate is not None else None
    if diff is None:
        for li in existing:
            proforma.line_items.remove(li)
            db.delete(li)
        return
    if existing:
        li = existing[0]
        li.rate, li.quantity = diff, Decimal("1")
        recalc(li, Decimal("0"))
        return
    charge = db.query(ChargeMasterEntry).filter(ChargeMasterEntry.code == GST_DIFFERENCE_CODE).first()
    if charge is None:
        return
    li = new_line(proforma, charge, diff, Decimal("1"), gst_amount=Decimal("0"))
    db.add(li)
    proforma.line_items.append(li)


def container_count(shipment) -> Optional[Decimal]:
    """Shipment's 'Cntr' as a number (it's free text in the tracker, e.g. '5')."""
    m = re.search(r"\d+", shipment.container or "") if shipment else None
    return Decimal(m.group()) if m and int(m.group()) > 0 else None

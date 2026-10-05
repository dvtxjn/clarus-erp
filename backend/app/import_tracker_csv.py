"""
Import the client's Google-Sheets tracker export into shipments.
Run with: python -m app.import_tracker_csv "<path to .csv>" [--dry-run]

Re-runnable: rows are matched to existing shipments by MBL and updated in
place, so importing a fresher export doesn't create duplicates.

Mapping decisions (sheet column -> Shipment):
  - every sheet column has its own field ('line' -> shipping_line); 'day' is
    computed by the app (Shipment.days), not imported
  - `port` = the IN-code at the start of 'pod' (e.g. 'INDWN6 - Panipat' -> INDWN6)
  - `status` isn't filled in the sheet, so it's derived from the flags:
    cntr status OUT -> Cleared; OOC? -> OOC Done; duty paid? -> Duty Paid;
    BE no -> BE Filed; IGM -> IGM Filed; else To be Filed
  - blank Job (upcoming shipments with no job number yet) -> ''
  - every row gets the tyre HS code (all current shipments are tyre scrap)
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date, datetime
from typing import Optional

from app.core.database import SessionLocal
from app.core.migrate import run_migrations
from app.core.enums import ShipmentStatus
from app.models.document import HSCode
from app.models.shipment import Shipment
from app.seed import TYRE_HS_CODE


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _date(v: Optional[str]) -> Optional[date]:
    v = _clean(v)
    if not v:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    return None


def _name(v: Optional[str]) -> Optional[str]:
    """Client/consignee: also normalise hyphen spacing ('A-B' / 'A - B ' -> 'A - B')
    so sheet typos don't create duplicate names."""
    v = _clean(v)
    return re.sub(r"\s*-\s*", " - ", v) if v else v


def _yes(v: Optional[str]) -> bool:
    return (_clean(v) or "").lower() in ("yes", "y", "true")


def _status(r: dict) -> ShipmentStatus:
    if (_clean(r["cntr status"]) or "").upper() == "OUT":
        return ShipmentStatus.CLEARED
    if _yes(r["ooc?"]):
        return ShipmentStatus.OOC_DONE
    if _yes(r["duty paid?"]):
        return ShipmentStatus.DUTY_PAID
    if _clean(r["be no"]):
        return ShipmentStatus.BE_FILED
    if _clean(r["igm"]):
        return ShipmentStatus.IGM_FILED
    return ShipmentStatus.TO_BE_FILED


def _normalize_headers(fieldnames):
    # Sheet headers contain embedded newlines ("duty\npaid?") and stray spaces.
    return [re.sub(r"\s+", " ", h).strip().lower() for h in fieldnames]


def row_to_fields(r: dict) -> dict:
    pod = _clean(r["pod"])
    port_m = re.match(r"(IN[A-Z]{3}\d)", (pod or "").upper())
    return dict(
        job=_clean(r["job"]) or "",
        mbl=_clean(r["mbl"]),
        be_description=_clean(r["be description"]),
        eta=_date(r["eta"]),
        inw=_clean(r["inw"]),
        license=_clean(r["license"]),
        client=_name(r["client"]),
        consignee=_name(r["consignee"]),
        pod=pod,
        port=port_m.group(1) if port_m else None,
        container_status=_clean(r["cntr status"]),
        cfs=_clean(r["cfs"]),
        be_no=_clean(r["be no"]),
        be_dt=_date(r["be dt"]),
        container=_clean(r["cntr"]),
        gross_wt=_clean(r["gross wt"]),
        poc=_clean(r["poc"]),
        remark=_clean(r["remark"]),
        remarks=_clean(r["remarks"]),
        mbl_date=_date(r["mbl date"]),
        hbl_date=_date(r["hbl date"]),
        gw=_clean(r["gw"]),
        total_pkg=_clean(r["total pkg"]),
        pkg_code=_clean(r["pkg code"]),
        line_no=_clean(r["line no"]),
        igm_date=_date(r["igm date"]),
        voyage=_clean(r["voyage"]),
        cont=_clean(r["cont"]),
        shipping_line=_clean(r["line"]),
        cleared_date=_date(r["cleared date"]),
        duty_paid=_yes(r["duty paid?"]),
        cfs_inv_received=_yes(r["cfs inv?"]),
        line_paid=_yes(r["line paid?"]),
        ooc=_yes(r["ooc?"]),
        do=_yes(r["do?"]),
        igm=_clean(r["igm"]),
        delivery_status=_clean(r["delivery"]),
        status=_status(r),
    )


def import_csv(path: str, dry_run: bool = False) -> dict:
    run_migrations()
    db = SessionLocal()
    stats = {"created": 0, "updated": 0, "skipped": []}
    try:
        hs = db.query(HSCode).filter(HSCode.code == TYRE_HS_CODE).first()
        with open(path, newline="", encoding="utf-8-sig") as f:
            from app.tracker_import import mbl_keys as _mbl_keys  # BHMA… = HDMUBHMA…
            reader = csv.reader(f)
            headers = _normalize_headers(next(reader))
            for n, raw in enumerate(reader, start=2):
                r = dict(zip(headers, raw + [""] * (len(headers) - len(raw))))
                fields = row_to_fields(r)
                if not fields["mbl"]:
                    stats["skipped"].append(f"row {n}: no MBL")
                    continue
                existing = db.query(Shipment).filter(Shipment.mbl.in_(_mbl_keys(fields["mbl"]))).first()
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    stats["updated"] += 1
                else:
                    shipment = Shipment(**fields, hs_code_id=hs.id if hs else None)
                    shipment.apply_hss_from_consignee()  # "SELLER - BUYER" consignee = HSS
                    db.add(shipment)
                    stats["created"] += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    return stats


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    result = import_csv(sys.argv[1], dry_run="--dry-run" in sys.argv)
    print(result)

"""
Read everything ICEGATE has for one shipment and put it where it belongs (client, 2026-09-30):

- Sea IGM (MBL + port; for inland shipments the port is the gateway the ICD BL status names, e.g. INMUN1)
  → the IGM details on the shipment (app/igm/apply.py).
- Inland only — ICD BL status (MBL only) → the containers' arrival at the FPOD (shipment_containers), and
  shipment.icegate["icd"]: only what the IGM details don't already hold (the ICD's own IGM, SMTP, BE
  location, importer…). Values both sources carry are compared: equal → left out; different → listed
  in shipment.icegate["differences"].
- For inland shipments the tracker's IGM column holds the ICD IGM, so the sea (gateway) IGM number goes to
  shipment.icegate["gateway_igm"] instead of overwriting it.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app import alerts, liners
from app.igm import apply as igm_apply, icd, sea
from app.models.shipment import Shipment


def _dmy(v) -> Optional[str]:
    if isinstance(v, date):
        return v.strftime("%d-%b-%Y")
    return v or None


# (label, sea key, icd key) — values both sources carry; shown once in the IGM details
SHARED = [
    ("Line no", "line_no", "line_no"),
    ("Sub-line", "sub_line_no", "sub_line_no"),
    ("MBL date", "mbl_date", "mbl_date"),
    ("Packages", "total_package", "total_package"),
    ("Package code", "package_code", "package_code"),
    ("Gross weight", "gross_weight", "gross_weight"),
    ("Inward (gateway)", "inw_date", "inward_date"),
    ("Destination", "port_dest", "icd"),
    ("Cargo movement", "cargo_movement", "cargo_movement"),
]


def _num_equal(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.001
    except ValueError:
        return a.strip().upper() == b.strip().upper()


def refresh(db: Session, s: Shipment, user_id: Optional[int]) -> dict:
    """Fetch + write. Returns a summary for the page. Does not commit."""
    from app.routers.containers import merge_icd  # late: the router imports app.igm

    inland = (s.port or "").upper() not in alerts.SEA_PORTS
    summary: dict = {"inland": inland, "sea_found": False, "icd_found": False, "changed": {}, "notes": []}
    known = liners.identify(s.mbl)
    if known and known["note"]:
        summary["hint"] = known["note"]  # e.g. HMM without HDMU, an HBL in the MBL column
    # HMM typed without HDMU: search ICEGATE with the prefix (client, 2026-09-30); the MBL itself isn't changed
    mbl = (known or {}).get("icegate_mbl") or s.mbl
    if mbl != s.mbl:
        summary["looked_up_as"] = mbl
    record: dict = {"fetched_at": datetime.now().isoformat(timespec="minutes")}

    location = s.port
    icd_bl = None
    if inland:
        got = icd.fetch(mbl)
        summary["icd_found"] = got["found"]
        if got["found"]:
            icd_bl = {k: _dmy(v) for k, v in got["bls"][0].items()}
            location = icd_bl.get("gateway_port") or location
            added, updated, kept = merge_icd(db, s.id, got["containers"], user_id)
            summary["containers"] = {"added": added, "updated": updated, "kept_manual": kept}

    sea_data = sea.fetch(mbl, location) if location else {"status": "IGM Not Filed"}
    summary["sea_found"] = sea_data.get("status") == "IGM Filed"
    if summary["sea_found"]:
        if inland:
            record["gateway_igm"] = {"port": location, "no": sea_data.get("igm_no"), "date": sea_data.get("igm_date")}
            sea_for_fields = {**sea_data, "igm_no": None}  # the tracker's IGM column is the ICD IGM
        else:
            sea_for_fields = sea_data
        changed, notes = igm_apply.apply(db, s, sea_for_fields, user_id)
        summary["changed"] = {k: [str(o) if o is not None else None, str(n)] for k, (o, n) in changed.items()}
        summary["notes"] += notes
        record["vessel"] = {k: sea_data.get(k) for k in ("vessel_code", "imo_no", "voyage_no", "goods") if sea_data.get(k)}

    if icd_bl:
        differences = []
        for label, sk, ik in SHARED:
            a, b = sea_data.get(sk), icd_bl.get(ik)
            if a and b and not _num_equal(str(a), str(b)):
                differences.append({"field": label, "igm": a, "icd": b})
        shared_icd = {ik for _, _, ik in SHARED}
        record["icd"] = {
            k: v for k, v in {
                "icd_igm_no": icd_bl.get("igm_no"), "icd_igm_date": icd_bl.get("igm_date"),
                "smtp_no": icd_bl.get("smtp_no"), "smtp_date": icd_bl.get("smtp_date"),
                "gateway_port": icd_bl.get("gateway_port"), "be_location": icd_bl.get("be_location"),
                "importer": icd_bl.get("importer"),
                # carried only when the IGM side didn't have it
                **{ik: icd_bl.get(ik) for _, sk, ik in SHARED if ik in shared_icd and not sea_data.get(sk)},
            }.items() if v
        }
        record["differences"] = differences
        summary["differences"] = differences
    record["notes"] = summary["notes"]
    s.icegate = record
    return summary

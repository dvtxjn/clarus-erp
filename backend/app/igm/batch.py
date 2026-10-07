"""
ICEGATE, automatically (client, 2026-09-30): Cloud Scheduler calls POST /internal/jobs/icegate every ~6 hours.

Which shipments (live = not archived, no Cleared Date):
- sea ports: no inward date yet and the ETA within 4 days (or past) — the client's sheet rule — or inward
  but no containers on it yet (the container list comes from the sea IGM)
- inland (ICD): ETA within 4 days (or past) and not every container has arrived at the ICD yet
Cleared shipments (Cleared Date set, on or before today) are read once more, then marked final
(icegate["final"]) and never read again — not by the job, not by the button (client, 2026-10-07).
Each is read like the "Fetch from ICEGATE" button (app/igm/refresh.py), committed one by one, a pause between
them. The last run is kept in app_settings["icegate_last_run"] for the Settings page.
"""
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app import alerts
from app.core.database import SessionLocal
from app.igm import refresh
from app.models.container import ShipmentContainer
from app.models.settings import AppSetting
from app.models.shipment import Shipment

log = logging.getLogger("icegate")
AHEAD_DAYS = 4
PAUSE_SECONDS = 1.5  # be gentle with a public government site
FINAL_PER_RUN = 40  # cleared shipments' last read, a few at a time so the first run isn't hours long


def is_final(s: Shipment) -> bool:
    return bool((s.icegate or {}).get("final"))


def due_final(db: Session, today: Optional[date] = None) -> list[Shipment]:
    """Cleared shipments whose last ICEGATE read hasn't been done yet (oldest clearance first)."""
    today = today or date.today()
    rows = (db.query(Shipment)
            .filter(Shipment.cleared_date.isnot(None), Shipment.cleared_date <= today, Shipment.mbl.isnot(None))
            .order_by(Shipment.cleared_date, Shipment.id).all())
    return [s for s in rows if not is_final(s)][:FINAL_PER_RUN]


def finalise(s: Shipment, before: Optional[dict], summary: dict) -> None:
    """After a cleared shipment's read: mark it final. If ICEGATE no longer has it, keep the earlier read-out."""
    record = s.icegate or {}
    if not summary["sea_found"] and not summary["icd_found"] and before and (before.get("sea_found") or before.get("icd_found")):
        record = {k: v for k, v in before.items() if k not in ("error", "error_at")}
    s.icegate = {**record, "final": datetime.now().isoformat(timespec="minutes"),
                 "final_cleared_date": s.cleared_date.isoformat() if s.cleared_date else None}


def read(db: Session, s: Shipment, user_id: Optional[int], retry: bool = False) -> dict:
    """One shipment's read (button or job); a cleared shipment is marked final afterwards. Does not commit."""
    before = dict(s.icegate or {})
    summary = _refresh_with_retry(db, s) if retry else refresh.refresh(db, s, user_id)
    if s.cleared_date and s.cleared_date <= date.today():
        finalise(s, before, summary)
        summary["final"] = True
    return summary


def due(db: Session, today: Optional[date] = None) -> list[Shipment]:
    today = today or date.today()
    horizon = today + timedelta(days=AHEAD_DAYS)
    live = (db.query(Shipment)
            .filter(Shipment.is_archived.is_(False), Shipment.cleared_date.is_(None), Shipment.mbl.isnot(None))
            .all())
    picked = []
    for s in live:
        if not s.eta or s.eta > horizon:
            continue
        boxes = db.query(ShipmentContainer).filter(ShipmentContainer.shipment_id == s.id).all()
        if (s.port or "").upper() in alerts.SEA_PORTS:
            if alerts.parse_inw(s.inw) is None or not boxes:
                picked.append(s)
        else:
            if not boxes or any(c.arrival_date is None for c in boxes):
                picked.append(s)
    return picked


def _refresh_with_retry(db: Session, s: Shipment) -> dict:
    """ICEGATE sometimes drops a request: one more try after a pause before calling it a failure."""
    try:
        return refresh.refresh(db, s, None)
    except (httpx.HTTPError, ValueError):
        db.rollback()
        time.sleep(PAUSE_SECONDS * 4)
        return refresh.refresh(db, s, None)


def failure_text(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"ICEGATE answered {e.response.status_code}"
    if isinstance(e, httpx.HTTPError):
        return "ICEGATE didn't answer"
    return "ICEGATE's answer couldn't be read"


def record_failure(db: Session, s: Shipment, e: Exception) -> None:
    """Keep the last good read-out; add the failure (cleared by the next good lookup). Flagged on the dashboard."""
    s.icegate = {**(s.icegate or {}), "error": failure_text(e), "error_at": datetime.now().isoformat(timespec="minutes")}
    db.commit()


def run_auto() -> dict:
    """The 6-hourly job. Never raises for one bad shipment; returns (and stores) a summary."""
    db = SessionLocal()
    result = {"at": datetime.now().isoformat(timespec="minutes"), "checked": 0, "filled": 0, "not_found": 0,
              "errors": 0, "jobs": []}
    try:
        result["final"] = 0
        for s in due(db) + due_final(db):
            result["checked"] += 1
            try:
                summary = read(db, s, None, retry=True)
                result["final"] += 1 if summary.get("final") else 0
                db.commit()
                if summary["changed"] or summary.get("containers", {}).get("updated") or summary.get("containers", {}).get("added"):
                    result["filled"] += 1
                    result["jobs"].append(s.job or s.mbl)
                if not summary["sea_found"] and not summary["icd_found"]:
                    result["not_found"] += 1
            except (httpx.HTTPError, ValueError) as e:
                db.rollback()
                result["errors"] += 1
                log.warning("icegate: %s failed", s.mbl, exc_info=True)
                record_failure(db, s, e)
            time.sleep(PAUSE_SECONDS)
        row = db.get(AppSetting, "icegate_last_run") or AppSetting(key="icegate_last_run")
        row.value = result
        db.merge(row)
        db.commit()
        log.info("icegate auto: %s", result)
        return result
    finally:
        db.close()

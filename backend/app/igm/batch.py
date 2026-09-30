"""
ICEGATE, automatically (client, 2026-09-30): Cloud Scheduler calls POST /internal/jobs/icegate every ~6 hours.

Which shipments (live = not archived, no Cleared Date):
- sea ports: no inward date yet and the ETA within 4 days (or past) — the client's sheet rule — or inward
  but no containers on it yet (the container list comes from the sea IGM)
- inland (ICD): ETA within 4 days (or past) and not every container has arrived at the ICD yet
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


def run_auto() -> dict:
    """The 6-hourly job. Never raises for one bad shipment; returns (and stores) a summary."""
    db = SessionLocal()
    result = {"at": datetime.now().isoformat(timespec="minutes"), "checked": 0, "filled": 0, "not_found": 0,
              "errors": 0, "jobs": []}
    try:
        for s in due(db):
            result["checked"] += 1
            try:
                summary = refresh.refresh(db, s, None)
                db.commit()
                if summary["changed"] or summary.get("containers", {}).get("updated") or summary.get("containers", {}).get("added"):
                    result["filled"] += 1
                    result["jobs"].append(s.job or s.mbl)
                if not summary["sea_found"] and not summary["icd_found"]:
                    result["not_found"] += 1
            except (httpx.HTTPError, ValueError):
                db.rollback()
                result["errors"] += 1
                log.warning("icegate: %s failed", s.mbl, exc_info=True)
            time.sleep(PAUSE_SECONDS)
        row = db.get(AppSetting, "icegate_last_run") or AppSetting(key="icegate_last_run")
        row.value = result
        db.merge(row)
        db.commit()
        log.info("icegate auto: %s", result)
        return result
    finally:
        db.close()

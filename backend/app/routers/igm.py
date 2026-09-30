"""On command: read ICEGATE (sea IGM, and for inland shipments the ICD BL status) for one shipment."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.igm import batch
from app.models.settings import AppSetting
from app.igm import refresh as igm_refresh
from app.models.user import User
from app.routers.containers import _shipment
from app.schemas.shipment import ShipmentOut

router = APIRouter(prefix="/shipments/{shipment_id}/icegate", tags=["icegate"])


@router.post("/refresh")
def refresh_from_icegate(shipment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _shipment(db, shipment_id, user)
    if not s.mbl:
        raise HTTPException(status_code=400, detail="This shipment has no MBL")
    try:
        summary = igm_refresh.refresh(db, s, user.id)
    except httpx.HTTPError as e:
        db.rollback()
        batch.record_failure(db, s, e)
        raise HTTPException(status_code=502, detail="ICEGATE didn't answer — try again in a minute")
    db.commit()
    db.refresh(s)
    return {"summary": summary, "shipment": ShipmentOut.model_validate(s)}


status_router = APIRouter(prefix="/icegate", tags=["icegate"])


@status_router.get("/status")
def icegate_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Settings: the last automatic run, and which shipments the next one would read."""
    row = db.get(AppSetting, "icegate_last_run")
    return {
        "last_run": row.value if row else None,
        "every_hours": 6,
        "due_now": [{"id": s.id, "job": s.job, "mbl": s.mbl, "port": s.port} for s in batch.due(db)],
    }

"""On command: read ICEGATE (sea IGM, and for inland shipments the ICD BL status) for one shipment."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
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
    except httpx.HTTPError:
        db.rollback()
        raise HTTPException(status_code=502, detail="ICEGATE didn't answer — try again in a minute")
    db.commit()
    db.refresh(s)
    return {"summary": summary, "shipment": ShipmentOut.model_validate(s)}

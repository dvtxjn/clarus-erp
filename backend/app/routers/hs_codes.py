from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.document import HSCode
from app.models.user import User
from app.schemas.document import HSCodeOut

router = APIRouter(prefix="/hs-codes", tags=["hs-codes"])


@router.get("", response_model=list[HSCodeOut])
def list_hs_codes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Spec §3.1: "An HS-code management interface where new HS codes can be
    added, each with its own configurable list of required documents."
    Used to populate the HS-code picker on the shipment detail page and to
    drive the Document Manager checklist for a shipment's assigned code.
    """
    codes = db.query(HSCode).all()
    return [HSCodeOut.from_orm_with_docs(c) for c in codes]


@router.get("/{hs_code_id}", response_model=HSCodeOut)
def get_hs_code(hs_code_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    hs_code = db.query(HSCode).filter(HSCode.id == hs_code_id).first()
    if not hs_code:
        raise HTTPException(status_code=404, detail="HS code not found")
    return HSCodeOut.from_orm_with_docs(hs_code)

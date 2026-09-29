from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models.port import Port
from app.models.user import User

router = APIRouter(prefix="/ports", tags=["ports"])


class PortIn(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)


class PortOut(PortIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


@router.get("", response_model=List[PortOut])
def list_ports(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Port).order_by(Port.code).all()


@router.post("", response_model=PortOut, status_code=201)
def create_port(payload: PortIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    code = payload.code.strip().upper()
    if db.query(Port).filter(Port.code == code).first():
        raise HTTPException(status_code=400, detail="Port code already exists")
    port = Port(code=code, name=payload.name.strip())
    db.add(port)
    db.commit()
    db.refresh(port)
    return port


@router.put("/{port_id}", response_model=PortOut)
def update_port(port_id: int, payload: PortIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    port = db.get(Port, port_id)
    if not port:
        raise HTTPException(status_code=404, detail="Port not found")
    port.code, port.name = payload.code.strip().upper(), payload.name.strip()
    db.commit()
    db.refresh(port)
    return port

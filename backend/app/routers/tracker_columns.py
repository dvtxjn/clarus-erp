"""
Org-wide tracker column management: add custom columns, delete them, and
remove/restore built-in ones. Changes apply to everyone, so they're admin-only;
hiding a column just for yourself is done in the grid layout instead.
"""
import re
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models.shipment import Shipment
from app.models.tracker_column import TrackerColumn
from app.models.user import User

router = APIRouter(prefix="/tracker-columns", tags=["tracker columns"])

# Built-in fields that can't be removed from the tracker.
PROTECTED = {"mbl"}
BUILTIN_KEYS = {c.name for c in Shipment.__table__.columns} - {"id", "custom_fields"}


class TrackerColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    data_type: str
    is_custom: bool
    is_removed: bool


class CustomColumnCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    data_type: Literal["text", "date", "number", "boolean"] = "text"


class BuiltinRemove(BaseModel):
    key: str
    label: str = Field(min_length=1)


class ColumnRename(BaseModel):
    label: str = Field(min_length=1, max_length=60)


@router.get("", response_model=List[TrackerColumnOut])
def list_columns(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(TrackerColumn).order_by(TrackerColumn.id).all()


@router.post("", response_model=TrackerColumnOut, status_code=201)
def add_custom_column(payload: CustomColumnCreate, db: Session = Depends(get_db),
                      _admin: User = Depends(require_admin)):
    label = payload.label.strip()
    base = "c_" + (re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "column")
    key, n = base, 2
    while db.query(TrackerColumn).filter(TrackerColumn.key == key).first():
        key, n = f"{base}_{n}", n + 1
    col = TrackerColumn(key=key, label=label, data_type=payload.data_type, is_custom=True)
    db.add(col)
    db.commit()
    db.refresh(col)
    return col


@router.patch("/{key}", response_model=TrackerColumnOut)
def rename_custom_column(key: str, payload: ColumnRename, db: Session = Depends(get_db),
                         _admin: User = Depends(require_admin)):
    col = _custom_or_404(db, key)
    col.label = payload.label.strip()
    db.commit()
    db.refresh(col)
    return col


@router.delete("/{key}", status_code=204)
def delete_custom_column(key: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Deletes a custom column AND every value stored in it."""
    col = _custom_or_404(db, key)
    for s in db.query(Shipment).order_by(Shipment.id).with_for_update().populate_existing():  # id order
        if s.custom_fields and key in s.custom_fields:
            s.custom_fields = {k: v for k, v in s.custom_fields.items() if k != key}
    db.delete(col)
    db.commit()


@router.post("/remove-builtin", response_model=TrackerColumnOut)
def remove_builtin(payload: BuiltinRemove, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Take a built-in column off the tracker for everyone. Data is kept."""
    if payload.key not in BUILTIN_KEYS:
        raise HTTPException(status_code=404, detail="Unknown column")
    if payload.key in PROTECTED:
        raise HTTPException(status_code=400, detail="This column can't be removed")
    col = _builtin_row(db, payload.key)
    if col is None:
        col = TrackerColumn(key=payload.key, label=payload.label, is_custom=False)
        db.add(col)
    col.is_removed = True
    db.commit()
    db.refresh(col)
    return col


@router.post("/restore-builtin/{key}", response_model=TrackerColumnOut)
def restore_builtin(key: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    col = _builtin_row(db, key)
    if col is None:
        raise HTTPException(status_code=404, detail="Column isn't removed")
    col.is_removed = False
    db.commit()
    db.refresh(col)
    return col


def _custom_or_404(db: Session, key: str) -> TrackerColumn:
    col = db.query(TrackerColumn).filter(TrackerColumn.key == key, TrackerColumn.is_custom.is_(True)).first()
    if not col:
        raise HTTPException(status_code=404, detail="Custom column not found")
    return col


def _builtin_row(db: Session, key: str) -> Optional[TrackerColumn]:
    return db.query(TrackerColumn).filter(TrackerColumn.key == key, TrackerColumn.is_custom.is_(False)).first()

"""Admin switches (client, 2026-09-30): read by billing users, changed by the admin only."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.models.settings import DEFAULTS, AppSetting, all_settings
from app.models.user import User

router = APIRouter(tags=["settings"])


class SettingIn(BaseModel):
    value: Any


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    return all_settings(db)


@router.put("/settings/{key}")
def write_setting(key: str, payload: SettingIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if key not in DEFAULTS:
        raise HTTPException(status_code=404, detail="Unknown setting")
    if isinstance(DEFAULTS[key], bool) and not isinstance(payload.value, bool):
        raise HTTPException(status_code=422, detail="This setting is on / off")
    row = db.get(AppSetting, key)
    old = row.value if row is not None else DEFAULTS[key]
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = payload.value
    record_change(db, "app_settings", 0, key, old, payload.value, user.id)
    db.commit()
    return all_settings(db)

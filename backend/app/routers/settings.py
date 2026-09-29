"""Admin switches (client, 2026-09-30): read by billing users, changed by the admin only."""
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin, require_billing_access
from app.models.settings import AppSetting, all_settings, defaults
from app.models.user import User

router = APIRouter(tags=["settings"])


class SettingIn(BaseModel):
    value: Any


def _check(key: str, v: Any) -> None:
    """Each setting has a shape; refuse anything else (these are printed on invoices)."""
    ok = True
    if key == "e_invoicing":
        ok = isinstance(v, bool)
    elif key == "company":
        need = ("name", "gstin", "pan", "state_code", "state")
        ok = (isinstance(v, dict) and all(isinstance(v.get(k), str) and v[k].strip() for k in need)
              and isinstance(v.get("address_lines"), list) and all(isinstance(x, str) for x in v["address_lines"])
              and all(isinstance(v.get(k, ""), str) for k in ("cin", "email", "phone")))
        if ok and not re.fullmatch(r"\d{2}[A-Z0-9]{13}", v["gstin"].strip().upper()):
            raise HTTPException(status_code=422, detail="GSTIN should be 15 characters, starting with the 2-digit state code")
        if ok and not re.fullmatch(r"\d{2}", v["state_code"].strip()):
            raise HTTPException(status_code=422, detail="State code is 2 digits, e.g. 27")
    elif key == "bank":
        ok = isinstance(v, list) and all(isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r) for r in v)
    elif key in ("final_terms", "proforma_notes"):
        ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
    if not ok:
        raise HTTPException(status_code=422, detail="That value doesn't fit this setting")


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _user: User = Depends(require_billing_access)):
    return all_settings(db)


@router.put("/settings/{key}")
def write_setting(key: str, payload: SettingIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if key not in defaults():
        raise HTTPException(status_code=404, detail="Unknown setting")
    _check(key, payload.value)
    row = db.get(AppSetting, key)
    old = row.value if row is not None else defaults()[key]
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = payload.value
    record_change(db, "app_settings", 0, key, old, payload.value, user.id)
    db.commit()
    return all_settings(db)


@router.get("/settings/system")
def system_status(db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    """Read-only facts for Settings → Storage & backups (changed on the server, not here)."""
    import os

    from app import backups, storage

    roots = storage.roots() if storage.backend() == "drive" else {}
    link = lambda fid: f"https://drive.google.com/drive/folders/{fid}" if fid else None  # noqa: E731
    return {
        "storage": storage.backend(),
        "drive_folders": {k: link(v) for k, v in roots.items()},
        "backups": backups.status(),
        "environment": os.getenv("APP_ENV", "development"),
        "public_url": os.getenv("PUBLIC_URL") or None,
    }

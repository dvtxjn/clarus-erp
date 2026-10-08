"""Admin switches (client, 2026-09-30): read by billing users, changed by the admin only."""
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin, require_billing_access
from app.models.settings import AppSetting, all_settings, defaults, get_setting
from app.models.user import User

router = APIRouter(tags=["settings"])


class SettingIn(BaseModel):
    value: Any


def _check(key: str, v: Any) -> None:
    """Each setting has a shape; refuse anything else (these are printed on invoices)."""
    ok = True
    if key in ("e_invoicing", "tds_rate_editable"):
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


@router.get("/settings/public")
def read_public_settings(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """The few switches every signed-in user's screens need (no invoice details)."""
    return {"tds_rate_editable": bool(get_setting(db, "tds_rate_editable"))}


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


class MirrorIn(BaseModel):
    link: str


def _mirror_out(db: Session) -> dict:
    from app import sheets_mirror
    from app.storage.drive_client import DriveError, load_service_account

    try:
        email = load_service_account().get("client_email")
    except (DriveError, OSError, ValueError):
        email = None
    row = db.get(AppSetting, sheets_mirror.KEY)
    st = dict(row.value or {}) if row else {}
    sid = st.get("sheet_id")
    return {**st, "link": f"https://docs.google.com/spreadsheets/d/{sid}" if sid else None,
            "share_with": email, "every_minutes": 15}


@router.get("/sheets-mirror")
def sheets_mirror_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Settings → Google Sheets copy of the tracker."""
    return _mirror_out(db)


@router.put("/sheets-mirror")
def set_sheets_mirror(payload: MirrorIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Paste the sheet link (empty = stop the copy). Writes once straight away so a sharing mistake shows."""
    from app import sheets_mirror

    sid = sheets_mirror.sheet_id_from(payload.link) if payload.link.strip() else None
    if payload.link.strip() and not sid:
        raise HTTPException(status_code=422, detail="That doesn't look like a Google Sheets link")
    row = db.get(AppSetting, sheets_mirror.KEY)
    old = dict(row.value or {}) if row else {}
    if row is None:
        row = AppSetting(key=sheets_mirror.KEY)
        db.add(row)
    # a different sheet starts from a clean slate (no rows to blank)
    row.value = {"sheet_id": sid} if sid != old.get("sheet_id") else {**old, "sheet_id": sid}
    record_change(db, "app_settings", 0, sheets_mirror.KEY, old.get("sheet_id"), sid, user.id)
    db.commit()
    if sid:
        sheets_mirror.mirror(db)
    return _mirror_out(db)


@router.post("/sheets-mirror/run")
def run_sheets_mirror(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    from app import sheets_mirror

    sheets_mirror.mirror(db)
    return _mirror_out(db)


# --- automatic update rules (client, 2026-09-30): IF … THEN …, admin-editable ---
@router.get("/auto-rules")
def get_auto_rules(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    from app import auto_rules

    return auto_rules.describe(db)


@router.put("/auto-rules")
def put_auto_rules(body: dict[str, Any], db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from app import auto_rules

    try:
        new = auto_rules.validate(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    row = db.get(AppSetting, auto_rules.KEY)
    old = row.value if row else None
    db.merge(AppSetting(key=auto_rules.KEY, value=new))
    record_change(db, "app_settings", 0, auto_rules.KEY, str(old), str(new), admin.id)
    db.commit()
    return auto_rules.describe(db)



@router.post("/settings/ooc-interest")
def ooc_interest_backfill(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Admin, one click: read the interest (INT) on OOC copies uploaded before it was read; fixes the duty
    without interest where it's still the OOC total. See app/extraction/ooc_interest.py."""
    from app.extraction.ooc_interest import backfill_ooc_interest

    return backfill_ooc_interest(db, user.id)

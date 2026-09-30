"""The ICEGATE login the ERP uses for its own lookups (BE status, queries, challans) — admin and import managers."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin, require_icegate_access
from app.icegate_portal import sync
from app.models.user import User

router = APIRouter(prefix="/icegate-login", tags=["icegate-login"])


def _out(db: Session) -> dict:
    _, lg = sync.login_state(db)
    _, st = sync._state(db)
    c = sync.credentials(db)
    who = db.get(User, lg["password_set_by"]).full_name if lg.get("password_set_by") and db.get(User, lg["password_set_by"]) else None
    return {"icegate_id": c["icegate_id"] or None, "cha_code": c["cha_code"] or None, "password_set": bool(c["password"]),
            "password_set_at": lg.get("password_set_at"), "password_set_by": who, "password_bad": bool(lg.get("password_bad")),
            "bad_since": lg.get("bad_since"), "last_login": st.get("last_login"), "last_status": st.get("last_status"),
            "last_challans": st.get("last_challans"), "last_error": st.get("last_error"), "ready": sync.ready(db)}


@router.get("")
def status(db: Session = Depends(get_db), _u: User = Depends(require_icegate_access)):
    return _out(db)


class PasswordIn(BaseModel):
    password: str = Field(min_length=4, max_length=128)


@router.put("/password")
def change_password(payload: PasswordIn, db: Session = Depends(get_db), user: User = Depends(require_icegate_access)):
    """ICEGATE resets the password periodically: enter the new one here (it's never shown again)."""
    sync.set_password(db, payload.password, user.id)
    return _out(db)


class LoginIn(BaseModel):
    icegate_id: Optional[str] = Field(None, max_length=40)  # either can be changed alone; blank = keep
    cha_code: Optional[str] = Field(None, max_length=40)


@router.put("")
def set_login(payload: LoginIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    from app.core.audit import record_change

    row, lg = sync.login_state(db)
    old = (lg.get("icegate_id"), lg.get("cha_code"))
    for field in ("icegate_id", "cha_code"):
        v = "".join((getattr(payload, field) or "").split()).upper()
        if v and not (6 <= len(v) <= 40 and v.isalnum()):
            raise HTTPException(status_code=422, detail=f"{'ICEGATE ID' if field == 'icegate_id' else 'CHA code'} should be 6–40 letters and digits")
        if v:
            lg[field] = v
    row.value = lg
    record_change(db, "app_settings", 0, sync.LOGIN_KEY, " / ".join(filter(None, old)) or None,
                  " / ".join(filter(None, (lg.get("icegate_id"), lg.get("cha_code")))), user.id)
    db.commit()
    return _out(db)


class RunIn(BaseModel):
    what: Literal["status", "challans"] = "status"


@router.post("/run")
def run_now(payload: RunIn, db: Session = Depends(get_db), _u: User = Depends(require_icegate_access)):
    if not sync.ready(db):
        raise HTTPException(status_code=400, detail="Set the ICEGATE login first" if not sync.credentials(db)["password"]
                            else "The ICEGATE password needs updating first")
    sync.run(db, payload.what, force=True)
    return _out(db)

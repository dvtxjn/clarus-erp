"""ICEGATE mails: import (.eml / Gmail zip), the feed, a shipment's customs timeline, marking attention done."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_user_allowed_ports, require_admin
from app.icegate_mail import apply as mail_apply
from app.models.icegate_mail import IcegateMail
from app.models.shipment import Shipment
from app.models.user import User
from app.routers.containers import _shipment

router = APIRouter(tags=["icegate-mail"])


class MailOut(BaseModel):
    id: int
    received_at: Optional[datetime] = None
    kind: str
    label: str
    summary: Optional[str] = None
    be_no: Optional[str] = None
    be_date: Optional[date] = None
    job_no: Optional[str] = None
    port: Optional[str] = None
    mbl: Optional[str] = None
    detail: Optional[dict] = None
    notes: Optional[list] = None
    shipment_id: Optional[int] = None
    shipment_job: Optional[str] = None
    shipment_mbl: Optional[str] = None
    shipment_be_no: Optional[str] = None
    client: Optional[str] = None
    document_id: Optional[int] = None
    attention: bool
    resolved_at: Optional[datetime] = None
    resolved_note: Optional[str] = None


OTP_VALID = timedelta(minutes=10)


def _out(m: IcegateMail, s: Optional[Shipment], user: Optional[User] = None) -> MailOut:
    o = MailOut.model_validate(m, from_attributes=True)
    if m.kind == "otp":
        # login code: admin only, and only while ICEGATE says it's valid
        d = dict(m.detail or {})
        got = m.received_at if (m.received_at is None or m.received_at.tzinfo) else m.received_at.replace(tzinfo=timezone.utc)
        live = got is not None and datetime.now(timezone.utc) - got < OTP_VALID
        is_admin = user is not None and user.role.value == "admin"
        if not (live and is_admin):
            d.pop("otp", None)
        d["otp_expired"] = not live
        o.detail = d
    if s:
        o.shipment_job, o.shipment_mbl, o.shipment_be_no, o.client = s.job, s.mbl, s.be_no, s.client
    return o


@router.post("/icegate-mails/import")
async def import_mails(files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    """Admin: .eml files, or the zip Gmail gives for "Download all" attachments."""
    raws: list[bytes] = []
    for f in files:
        data = await f.read()
        if len(data) > 200 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} is too large")
        try:
            raws.extend(mail_apply.unpack(f.filename or "", data))
        except Exception:  # noqa: BLE001 — a broken zip
            raise HTTPException(status_code=422, detail=f"Couldn't open {f.filename}")
    if not raws:
        raise HTTPException(status_code=422, detail="No .eml mails found — upload .eml files or a zip of them")
    return mail_apply.import_mails(db, raws, user)


@router.get("/icegate-mails", response_model=list[MailOut])
def list_mails(attention: bool = Query(False, description="Open attention items only"),
               unmatched: bool = Query(False), limit: int = Query(300, le=2000),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The feed, newest first. Port-scoped users see their ports' mails (unmatched ones: admin only)."""
    q = db.query(IcegateMail)
    if attention:
        q = q.filter(IcegateMail.attention.is_(True), IcegateMail.resolved_at.is_(None))
    if unmatched:
        q = q.filter(IcegateMail.shipment_id.is_(None))
    rows = q.order_by(IcegateMail.received_at.desc().nullslast(), IcegateMail.id.desc()).limit(limit).all()
    ships = {s.id: s for s in db.query(Shipment).filter(Shipment.id.in_({m.shipment_id for m in rows if m.shipment_id}))}
    allowed = get_user_allowed_ports(user)
    out = []
    for m in rows:
        s = ships.get(m.shipment_id)
        if allowed is not None and (s is None or s.port not in allowed):
            continue
        if m.kind == "otp" and user.role.value != "admin":
            continue
        out.append(_out(m, s, user))
    return out


@router.get("/shipments/{shipment_id}/icegate-mails", response_model=list[MailOut])
def shipment_mails(shipment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Customs timeline for one shipment, oldest first."""
    s = _shipment(db, shipment_id, user)
    rows = (db.query(IcegateMail).filter(IcegateMail.shipment_id == s.id)
            .order_by(IcegateMail.received_at.asc().nullsfirst(), IcegateMail.id).all())
    return [_out(m, s, user) for m in rows]


class ResolveIn(BaseModel):
    note: Optional[str] = None


@router.post("/icegate-mails/{mail_id}/resolve", response_model=MailOut)
def resolve(mail_id: int, payload: ResolveIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.get(IcegateMail, mail_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mail not found")
    s = _shipment(db, m.shipment_id, user) if m.shipment_id else None
    if s is None and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Only the admin can close unmatched mails")
    m.resolved_at = datetime.now(timezone.utc)
    m.resolved_by_id = user.id
    m.resolved_note = (payload.note or "").strip()[:300] or "Done"
    db.commit()
    return _out(m, s, user)


class LinkIn(BaseModel):
    shipment_id: int


@router.post("/icegate-mails/{mail_id}/link", response_model=MailOut)
def link_mail(mail_id: int, payload: LinkIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Admin: put an unmatched mail on its shipment by hand (then it's applied like any other)."""
    m = db.get(IcegateMail, mail_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mail not found")
    s = _shipment(db, payload.shipment_id, user)
    if m.shipment_id and m.shipment_id != s.id:
        raise HTTPException(status_code=409, detail="This mail is already on another shipment")
    m.shipment_id = s.id
    mail_apply.link(db, m, user)
    db.commit()
    return _out(m, s, user)


# --- the ICEGATE mailbox, read automatically (admin connects it once) ---
import os  # noqa: E402
import time as _time  # noqa: E402

from fastapi import Request  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from jose import JWTError, jwt  # noqa: E402

from app.core.security import ALGORITHM, SECRET_KEY  # noqa: E402
from app.icegate_mail import gmail  # noqa: E402

CALLBACK = "/oauth/gmail/callback"


def _backend_base(request: Request) -> str:
    return (os.getenv("PUBLIC_URL") or str(request.base_url)).rstrip("/")


def _site() -> str:
    return (os.getenv("PUBLIC_URL") or "http://localhost:5173").rstrip("/")


def _reader_out(db: Session) -> dict:
    _, st = gmail.state(db)
    return {"mailbox": st.get("mailbox"), "connected": bool(st.get("token")), "connected_at": st.get("connected_at"),
            "last_run": st.get("last_run"), "last_error": st.get("last_error"), "last_new": st.get("last_new"),
            "instant": bool(gmail.topic_name()) and bool(st.get("watch_expires")) and not st.get("push_error"),
            "watch_expires": st.get("watch_expires"),
            "ready": bool(gmail.client_id() and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"))}


@router.get("/gmail-reader")
def reader_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return _reader_out(db)


@router.get("/gmail-reader/connect")
def reader_connect(request: Request, login_hint: Optional[str] = None, user: User = Depends(require_admin)):
    """The Google sign-in link for the mailbox (read-only permission)."""
    if not gmail.client_id() or not os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"):
        raise HTTPException(status_code=400, detail="Google sign-in isn't set up on the server yet (see the setup steps)")
    token = jwt.encode({"sub": str(user.id), "purpose": "gmail", "exp": int(_time.time()) + 600}, SECRET_KEY, algorithm=ALGORITHM)
    return {"url": gmail.auth_url(_backend_base(request) + CALLBACK, token, login_hint)}


@router.get(CALLBACK, include_in_schema=False)
def reader_callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    """Google sends the admin back here after they allow read access."""
    back = _site() + "/settings"
    try:
        claims = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
        if claims.get("purpose") != "gmail":
            raise JWTError("wrong purpose")
        admin = db.get(User, int(claims["sub"]))
        if admin is None or admin.role.value != "admin":
            raise JWTError("not admin")
    except (JWTError, KeyError, ValueError):
        return RedirectResponse(back + "?mailbox=expired#mailbox")
    if error or not code:
        return RedirectResponse(back + "?mailbox=cancelled#mailbox")
    try:
        body = gmail.exchange(code, _backend_base(request) + CALLBACK)
        gmail.connect(db, body)
    except gmail.GmailError:
        return RedirectResponse(back + "?mailbox=failed#mailbox")
    gmail.sync(db, topic=gmail.topic_name())  # the last 30 days of ICEGATE mails, and start the instant push
    return RedirectResponse(back + "?mailbox=connected#mailbox")


@router.post("/gmail-reader/sync")
def reader_sync(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    gmail.sync(db, topic=gmail.topic_name())
    return _reader_out(db)


@router.post("/gmail-reader/disconnect")
def reader_disconnect(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Forget the mailbox (the ERP stops reading). Mails already read stay."""
    row, st = gmail.state(db)
    gmail.save(db, row, {"mailbox": st.get("mailbox"), "disconnected": True})
    return _reader_out(db)

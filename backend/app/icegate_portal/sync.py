"""
The self-updater (client, 2026-09-30): ICEGATE portal -> shipments, on its own.

  every 30 min, 08:00–22:00 IST   BE status of every live BE not yet out of charge (+ once more after OOC),
                                  then the query list
  daily, 09:00 IST                pending duty challans -> the daily challan list (duty comes ONLY from here)

BE status -> shipments.icegate["be_status"] (the ICEGATE status column) and evidence ICEGATE is consistent on
(client): paid -> Duty Paid; examined -> under examination + when; OOC -> OOC + OOC date (+ Duty Paid). Identifiers
and dates already typed are never overwritten — a different value is noted.
Queries -> "B/E Query" events (Needs attention until ICEGATE shows a reply), matched on BE no + BE date + port:
BE numbers are reused every year (client), so the number alone never matches.
Payment details on the BE status page are NOT used for duty (client: duty = the daily challan list).
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.status_rules import status_after_evidence_change
from app.icegate_portal.client import ROLE_CB, BadPassword, Portal, PortalError, SessionLapsed, day, na, ts
from app.models.settings import AppSetting
from app.models.shipment import Shipment

KEY = "icegate_portal"  # app_settings: session (encrypted), last_login, last_status, last_challans, last_error
LOGIN_KEY = "icegate_login"  # app_settings: icegate_id, cha_code, password (encrypted), password_set_at / _by, password_bad
IST = timezone(timedelta(hours=5, minutes=30))
HOURS = range(8, 22)   # 08:00–21:59 IST
OTP_WAIT = 300         # seconds: be patient, the OTP mail can be slow
# ICEGATE blocks the account for an hour after too many OTP requests (client, 2026-10-01: "only login into
# icegate ONCE, and then wait 15 minutes"). Every login attempt — good or bad, by hand or automatic — locks
# the next one out for LOGIN_GAP; a "limit exceeded" answer locks it out for LIMIT_PAUSE.
LOGIN_GAP = timedelta(minutes=15)
LIMIT_PAUSE = timedelta(minutes=60)


# --- saved state ---
def _state(db: Session) -> tuple[AppSetting, dict]:
    row = db.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value={})
        db.add(row)
        db.flush()  # a second lookup in the same session finds it
    return row, dict(row.value or {})


def _save(db: Session, row: AppSetting, st: dict) -> None:
    row.value = st
    db.commit()


def _fernet():
    from app.icegate_mail.gmail import _fernet as f

    return f()


def _load_session(st: dict) -> dict:
    import json

    if not st.get("session"):
        return {}
    try:
        return json.loads(_fernet().decrypt(st["session"].encode()))
    except Exception:  # noqa: BLE001 — key changed / garbage: log in again
        return {}


def _store_session(st: dict, session: dict) -> None:
    import json

    st["session"] = _fernet().encrypt(json.dumps(session).encode()).decode() if session else None


OTP_POLL = 3          # seconds between mailbox reads while waiting
OTP_SKEW = timedelta(minutes=2)  # ICEGATE's mail clock vs ours


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def otp_from_mailbox(db: Session, icegate_id: str = "", sleep: Callable[[float], None] = None,
                     clock: Callable[[], float] = None) -> Callable[[datetime, set], Optional[str]]:
    """Wait (up to OTP_WAIT in all) for the ICEGATE login OTP mail of THIS login request: a mail the reader
    stored after the request was made (id above the mark taken now), sent no earlier than the request, for our
    ICEGATE ID, never used before and not already tried. The newest one wins. The code is marked used."""
    import time

    from app.icegate_mail import gmail
    from app.models.icegate_mail import IcegateMail

    sleep = sleep or time.sleep
    clock = clock or time.time
    _, mb = gmail.state(db)
    if not mb.get("token"):
        raise PortalError("The ICEGATE mailbox isn't connected, so the login OTP can't be read — connect it in Settings → Mailbox")
    mark = db.query(IcegateMail.id).order_by(IcegateMail.id.desc()).limit(1).scalar() or 0
    deadline: list[float] = []

    def wait(since: datetime, tried: set) -> Optional[str]:
        if not deadline:
            deadline.append(clock() + OTP_WAIT)
        since = _aware(since)
        while True:
            gmail.sync(db)  # don't wait for the push: read the mailbox now
            db.expire_all()
            rows = (db.query(IcegateMail).filter(IcegateMail.kind == "otp", IcegateMail.id > mark)
                    .order_by(IcegateMail.received_at.desc(), IcegateMail.id.desc()).all())
            for m in rows:
                d = dict(m.detail or {})
                got = _aware(m.received_at)
                if not d.get("otp") or d.get("used_at") or d["otp"] in tried:
                    continue
                if got is not None and got < since - OTP_SKEW:
                    continue  # an older login's mail that only reached the mailbox now
                if icegate_id and d.get("icegate_id") and d["icegate_id"].upper() != icegate_id.upper():
                    continue
                d["used_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                m.detail = d
                db.commit()
                return d["otp"]
            if clock() >= deadline[0]:
                return None
            sleep(OTP_POLL)

    return wait


def login_state(db: Session) -> tuple[AppSetting, dict]:
    row = db.get(AppSetting, LOGIN_KEY)
    if row is None:
        row = AppSetting(key=LOGIN_KEY, value={})
        db.add(row)
        db.flush()
    return row, dict(row.value or {})


def credentials(db: Session) -> dict:
    import os

    _, lg = login_state(db)
    pw = ""
    if lg.get("password"):
        try:
            pw = _fernet().decrypt(lg["password"].encode()).decode()
        except Exception:  # noqa: BLE001 — key changed: needs entering again
            pw = ""
    return {"icegate_id": lg.get("icegate_id") or os.getenv("ICEGATE_ID", ""), "cha_code": lg.get("cha_code") or os.getenv("ICEGATE_CHA_CODE", ""),
            "password": pw, "role_id": int(os.getenv("ICEGATE_ROLE_ID", ROLE_CB)), "password_bad": bool(lg.get("password_bad"))}


def set_password(db: Session, password: str, user_id: int) -> None:
    """New ICEGATE password (it resets periodically). Clears the "needs updating" stop."""
    row, lg = login_state(db)
    lg.update(password=_fernet().encrypt(password.encode()).decode(), password_bad=False, bad_since=None,
              password_set_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), password_set_by=user_id)
    row.value = lg
    record_change(db, "app_settings", 0, LOGIN_KEY, None, "ICEGATE password changed", user_id)  # never the value
    prow, st = _state(db)
    st["session"] = None  # log in afresh with the new password
    prow.value = st
    db.commit()


def ready(db: Session) -> bool:
    c = credentials(db)
    return bool(c["icegate_id"] and c["cha_code"] and c["password"] and not c["password_bad"])


def login_locked_until(st: dict) -> Optional[datetime]:
    """When the next ICEGATE login may be tried (None = now)."""
    until = []
    if st.get("login_attempt_at"):
        until.append(datetime.fromisoformat(st["login_attempt_at"]) + LOGIN_GAP)
    if st.get("login_blocked_until"):
        until.append(datetime.fromisoformat(st["login_blocked_until"]))
    latest = max(until) if until else None
    return latest if latest and latest > datetime.now(timezone.utc) else None


def portal_session(db: Session, portal: Optional[Portal] = None, auto: bool = False) -> Portal:
    """A logged-in portal: the saved session kept alive, or a fresh login (OTP from the mailbox).
    At most one login every 15 minutes; automatic runs never log in again after a failed login."""
    row, st = _state(db)
    p = portal or Portal(credentials(db), _load_session(st))
    try:
        p.keep_alive()
    except SessionLapsed:
        # row lock: two jobs (or a job and a click) can't both decide to log in at the same moment
        db.commit()
        row = db.query(AppSetting).filter(AppSetting.key == KEY).with_for_update().one()
        st = dict(row.value or {})
        locked = login_locked_until(st)
        if locked:
            raise PortalError(f"ICEGATE login paused until {locked.astimezone(IST):%H:%M} — one login every 15 minutes, "
                              "so ICEGATE doesn't block the account for too many OTPs")
        if auto and st.get("login_failed"):
            raise PortalError("The last ICEGATE login failed — automatic logins are stopped until someone logs in from the Customs mail page")
        wait = otp_from_mailbox(db, credentials(db)["icegate_id"])  # mailbox not connected: stop before asking ICEGATE
        # marked BEFORE the OTP is asked for, and never cleared: a crash mid-login still counts as an attempt
        st["login_attempt_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        st["login_failed"] = True
        _save(db, row, st)
        try:
            p.login(wait)
        except BadPassword:
            lrow, lg = login_state(db)
            lg.update(password_bad=True, bad_since=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            lrow.value = lg
            db.commit()
            raise
        except PortalError as e:
            if any(w in str(e).lower() for w in ("limit", "exceed", "blocked", "too many", "attempt")):
                row, st = _state(db)
                st["login_blocked_until"] = (datetime.now(timezone.utc) + LIMIT_PAUSE).isoformat(timespec="seconds")
                _save(db, row, st)
            raise
        row, st = _state(db)
        st["login_failed"] = False
        st["last_login"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _store_session(st, p.session)
    _save(db, row, st)
    return p


def _label(cs: dict) -> str:
    """One line for the tracker column, most advanced step first."""
    if ts(cs.get("oocDate")):
        return f"OOC {ts(cs['oocDate']).strftime('%d-%b %H:%M')}"
    parts = []
    if na(cs.get("queryRaised")):
        parts.append("Query replied" if na(cs.get("queryReply")) else "Query raised — reply needed")
    if ts(cs.get("examDate")):
        parts.append(f"Examined {ts(cs['examDate']).strftime('%d-%b')}")
    if ts(cs.get("pymtDate")):
        parts.append(f"Duty paid {ts(cs['pymtDate']).strftime('%d-%b')}")
    elif ts(cs.get("assessDate")):
        parts.append(f"Assessed {ts(cs['assessDate']).strftime('%d-%b')}" + (" (system)" if cs.get("appraisement") == "SYSTEM" else ""))
    q = na(cs.get("currentQueue"))
    if q and q.upper() == "INS":
        parts.append("Under examination (INS)")
    elif q:
        parts.append(f"with {q}")
    return " · ".join(parts) or "Filed — not assessed yet"


def apply_be_status(db: Session, s: Shipment, data: dict, now: datetime) -> list[str]:
    cs = (data.get("currentStatusModel") or [{}])[0]
    bd = (data.get("beDetailsModel") or [{}])[0]
    record = {
        "fetched_at": now.isoformat(timespec="seconds"), "label": _label(cs),
        "queue": na(cs.get("currentQueue")), "appraisement": na(cs.get("appraisement")),
        "assessed_at": na(cs.get("assessDate")), "paid_at": na(cs.get("pymtDate")), "exam_at": na(cs.get("examDate")),
        "ooc_at": na(cs.get("oocDate")), "query": na(cs.get("queryRaised")), "query_reply": na(cs.get("queryReply")),
        "reply_date": na(cs.get("replyDate")), "first_check": na(bd.get("firstCheck")), "sec48": na(bd.get("sec48")),
        "group": na(bd.get("appraisingGroup")),
        "amendments": [{"date": a.get("amendmentDate"), "status": a.get("amendmentStatus")} for a in data.get("beAmendmentModel") or []],
        "edocs": [d.get("docDescription") for d in data.get("edocValidityModel") or [] if d.get("validity") == "Y"],
    }
    notes: list[str] = []

    def set_(field, value):
        old = getattr(s, field)
        if value is None or old == value:
            return
        record_change(db, "shipments", s.id, field, old, value, None)
        setattr(s, field, value)
        notes.append(field)

    from app import auto_rules  # each step is a rule the admin can switch off (Settings → Automatic rules)

    paid, exam, ooc = ts(cs.get("pymtDate")), ts(cs.get("examDate")), ts(cs.get("oocDate"))
    if (paid or ooc) and auto_rules.on(db, "status.duty_paid"):
        set_("duty_paid", True)
    # queue INS = with the inspection (examination) officer: under examination (client, 2026-09-30)
    if (exam or (na(cs.get("currentQueue")) or "").upper() == "INS") and auto_rules.on(db, "status.examination"):
        set_("under_examination", True)
        if exam and not s.examination_at:
            set_("examination_at", exam.strftime("%d/%m/%Y %H:%M"))
    # the admin's own rules on the queue code
    for r in auto_rules.matching_queue_rules(db, na(cs.get("currentQueue"))):
        if r.get("field"):
            set_(r["field"], True)
        if r.get("attention"):
            _rule_attention(db, s, r, now)
    if ooc and auto_rules.on(db, "status.ooc"):
        set_("ooc", True)
        if s.ooc_date is None:
            set_("ooc_date", ooc.date())
        elif s.ooc_date != ooc.date():
            record["note"] = f"ICEGATE OOC date {ooc.date():%d-%m-%Y}; tracker has {s.ooc_date:%d-%m-%Y} — not changed"
    new = status_after_evidence_change(s)
    if new:
        record_change(db, "shipments", s.id, "status", s.status, new, None)
        s.status = new
    prev = (s.icegate or {}).get("be_status") or {}
    # INS at any point in the BE's life = it was under examination (client): remembered across runs
    in_ins = (record["queue"] or "").upper() == "INS"
    record["was_ins"] = bool(prev.get("was_ins") or in_ins)
    if record["was_ins"] and not in_ins and not exam and "OOC" not in record["label"]:
        record["label"] += " · was under examination"
    if prev.get("label") != record["label"]:
        record["changed_at"] = record["fetched_at"]
    else:
        record["changed_at"] = prev.get("changed_at") or record["fetched_at"]
    s.icegate = {**(s.icegate or {}), "be_status": record}
    return notes


def due_for_status(db: Session) -> list[Shipment]:
    """Live BEs we can look up (BE no + date + port), not yet out of charge — or OOC in the tracker but
    ICEGATE's OOC time not read yet."""
    rows = (db.query(Shipment).filter(Shipment.is_archived.is_(False), Shipment.cleared_date.is_(None),
                                      Shipment.be_no.isnot(None), Shipment.be_dt.isnot(None), Shipment.port.isnot(None)).all())
    out = []
    for s in rows:
        bs = (s.icegate or {}).get("be_status") or {}
        if not bs.get("ooc_at"):
            out.append(s)
    return out


# --- queries ---
def _rule_attention(db: Session, s: Shipment, rule: dict, now: datetime) -> None:
    """An admin's queue rule raised Needs attention: one item per BE + queue (not one every half hour)."""
    from app.models.icegate_mail import IcegateMail

    fp = hashlib.sha256(f"queue-rule:{rule.get('id')}:{s.id}:{s.be_no}:{s.be_dt}:{rule['queue']}".encode()).hexdigest()
    if db.query(IcegateMail.id).filter(IcegateMail.fingerprint == fp).first():
        return
    db.add(IcegateMail(fingerprint=fp, kind="other", label=f"BE status: queue {rule['queue']}",
                       subject=f"BE {s.be_no} is in queue {rule['queue']}", received_at=now, be_no=s.be_no, be_date=s.be_dt,
                       port=s.port, shipment_id=s.id, applied=True, attention=True,
                       summary=f"ICEGATE shows BE {s.be_no} in queue {rule['queue']} (your automatic rule)",
                       detail={"source": "icegate portal", "rule": rule.get("id")}))


def apply_queries(db: Session, rows: list[dict], now: datetime) -> dict:
    """One "B/E Query" event per query (location + BE no + BE date + query no). Open until ICEGATE shows a reply."""
    from app import auto_rules
    from app.models.icegate_mail import IcegateMail

    out = {"new": 0, "replied": 0}
    if not auto_rules.on(db, "status.queries"):
        return out
    for q in rows:
        be, be_dt, loc, qno = str(q.get("beNo") or ""), day(q.get("beDt")), (q.get("location") or "").upper(), str(q.get("queryNumber") or "")
        if not be or be_dt is None:
            continue
        s = (db.query(Shipment).filter(Shipment.be_no == be, Shipment.be_dt == be_dt).all())
        s = [x for x in s if (x.port or "").upper() == loc] or s
        ship = s[0] if len(s) == 1 else None
        if ship is None and (now.date() - be_dt).days > 60:
            continue  # an old BE with the same number (numbers are reused every year) — not ours to track
        fp = hashlib.sha256(f"portal-query:{loc}:{be}:{be_dt}:{qno}".encode()).hexdigest()
        reply = na(q.get("reply"))
        m = db.query(IcegateMail).filter(IcegateMail.fingerprint == fp).first()
        if m is None:
            m = IcegateMail(fingerprint=fp, kind="be_query", label="B/E Query", subject=f"ICEGATE query {qno} on BE {be}",
                            received_at=ts(q.get("queryDt")) or now, be_no=be, be_date=be_dt, port=loc,
                            shipment_id=ship.id if ship else None, applied=True, attention=True,
                            summary=f"Query {qno}: {(q.get('queryText') or '').strip()}",
                            detail={"source": "icegate portal", "query": q.get("queryText"), "query_no": qno})
            db.add(m)
            out["new"] += 1
        d = dict(m.detail or {})
        if reply and d.get("reply") != reply:
            d["reply"] = reply
            m.notes = [f"Replied: {reply}"]
            if m.resolved_at is None:
                m.resolved_at, m.resolved_note = now, "Replied on ICEGATE"
                out["replied"] += 1
        m.detail = d
        # the mail about the same query closes too once ICEGATE shows the reply
        if reply:
            for x in db.query(IcegateMail).filter(IcegateMail.kind == "be_query", IcegateMail.be_no == be,
                                                  IcegateMail.resolved_at.is_(None), IcegateMail.id != m.id):
                if x.be_date in (None, be_dt):
                    x.resolved_at, x.resolved_note = now, "Replied on ICEGATE"
    return out


# --- challans ---
def apply_challans(db: Session, rows: list[dict], now: datetime) -> dict:
    """Pending challans -> the daily duty challan list. A row is added only when ICEGATE's figure differs from
    the BE's latest one (so a quiet day adds nothing)."""
    from app.invoice.build import latest_challan
    from app.models.challan import DutyChallan

    added = 0
    for c in rows:
        be = str(c.get("boeNumber") or "").strip()
        try:
            amount = Decimal(str(c.get("dutyAmount")))
        except (InvalidOperation, TypeError):
            continue
        if not be:
            continue
        last = latest_challan(db, be, day(c.get("boeDate")))
        if last and last.challan_no == str(c.get("challanNumber")) and Decimal(last.due_amount) == amount:
            continue
        db.add(DutyChallan(be_no=be, be_date=c.get("boeDate"), location_code=c.get("locationCode"), iec=c.get("iecCode"),
                           challan_no=str(c.get("challanNumber") or ""), due_amount=amount, source="icegate",
                           filename="ICEGATE (automatic)", uploaded_at=now.replace(tzinfo=None)))
        added += 1
    db.flush()
    if added:
        from app.routers.challans import _match, _refresh

        matched, _ = _match(db, [(str(c.get("boeNumber") or "").strip(), c.get("boeDate")) for c in rows])
        _refresh(db, matched)
    return {"pending": len(rows), "added": added}


# --- runs ---
def run(db: Session, what: str = "status", portal: Optional[Portal] = None, force: bool = False, auto: bool = False) -> dict:
    """what = "status" (BE status + queries) or "challans". Returns (and stores) a summary."""
    row, st = _state(db)
    now = datetime.now(timezone.utc)
    if portal is None and not ready(db):
        return st  # not set up, or the password needs updating (no retries: the account must not get locked)
    if what == "status" and not force and now.astimezone(IST).hour not in HOURS:
        return st
    summary: dict = {"at": now.isoformat(timespec="seconds"), "what": what}
    try:
        p = portal_session(db, portal, auto=auto)
        if what == "challans":
            summary.update(apply_challans(db, p.challans(), now))
        else:
            checked = changed = 0
            for s in due_for_status(db):
                data = p.be_status(s.port, s.be_no, s.be_dt)
                checked += 1
                if data is None:
                    s.icegate = {**(s.icegate or {}), "be_status": {"fetched_at": now.isoformat(timespec="seconds"),
                                                                   "label": "Not found on ICEGATE (check BE no / date / port)"}}
                    continue
                before = ((s.icegate or {}).get("be_status") or {}).get("label")
                apply_be_status(db, s, data, now)
                changed += before != s.icegate["be_status"]["label"]
                db.commit()
            summary.update(checked=checked, changed=changed, **{f"queries_{k}": v for k, v in apply_queries(db, p.queries(), now).items()})
        db.commit()
        row, st = _state(db)
        _store_session(st, p.session)
        st.update(last_error=None, **{f"last_{what}": summary})
    except BadPassword:
        db.rollback()
        row, st = _state(db)
        st.update(last_error="ICEGATE password has been reset — enter the new one on the Customs mail page")
    except (PortalError, httpx.HTTPError) as e:
        db.rollback()
        row, st = _state(db)
        st.update(last_error=f"{now.astimezone(IST):%d-%b %H:%M} {e}"[:300])
    _save(db, row, st)
    return st


def run_status() -> None:
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        run(db, "status", auto=True)


def run_challans() -> None:
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        run(db, "challans", auto=True)

"""
Read the ICEGATE mailbox automatically (client, 2026-09-30): every new mail is pushed to the ERP the moment it
arrives (Gmail watch -> Pub/Sub -> /internal/gmail/push), with a 15-minute catch-up as a safety net.

Access: READ-ONLY. The admin connects ONE mailbox (a company address the ICEGATE mails are forwarded to) with
Google's gmail.readonly permission — Google itself refuses any send, delete, label or mark-as-read. The ERP
keeps a refresh token for that mailbox only, encrypted with BACKUP_ENCRYPTION_KEY; nothing else is readable.

Nothing depends on read / unread: each run asks Gmail for everything added since the last run (historyId), and
a mail already imported is skipped (fingerprint). After downtime the next run catches up, oldest first.
"""
from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.models.settings import AppSetting

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
KEY = "gmail_reader"  # app_settings: mailbox, token (encrypted), history_id, watch_expires, last_run, last_error, …
QUERY = "from:icegate.gov.in"  # first connect: the last 30 days of ICEGATE mails
FIRST_LIMIT = 300   # first connect reads at most this many (newest last)
PACE = 0.3          # seconds between mails: ~200 a minute, far below Gmail's per-user limit
RUN_SECONDS = 240   # one check reads for at most 4 minutes; the rest next time


class GmailError(Exception):
    pass


def client_id() -> str:
    return os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")


def _fernet():
    from cryptography.fernet import Fernet

    key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    if not key:
        raise GmailError("BACKUP_ENCRYPTION_KEY is not set — needed to keep the mailbox token safe")
    return Fernet(key.encode())


def state(db: Session) -> tuple[AppSetting, dict]:
    row = db.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value={})
        db.add(row)
        db.flush()  # a second lookup in the same session finds it
    return row, dict(row.value or {})


def save(db: Session, row: AppSetting, st: dict) -> None:
    row.value = st
    db.commit()


# --- connecting (admin, once) ---
def auth_url(redirect_uri: str, state_token: str, login_hint: Optional[str]) -> str:
    q = {"client_id": client_id(), "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false", "state": state_token}
    if login_hint:
        q["login_hint"] = login_hint
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(q)


def exchange(code: str, redirect_uri: str) -> dict:
    secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not client_id() or not secret:
        raise GmailError("Google sign-in isn't set up on the server (GOOGLE_OAUTH_CLIENT_SECRET)")
    r = httpx.post(TOKEN_URI, data={"code": code, "client_id": client_id(), "client_secret": secret,
                                    "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, timeout=30)
    if r.status_code != 200:
        raise GmailError(f"Google refused the sign-in ({r.status_code})")
    body = r.json()
    if SCOPE not in body.get("scope", "").split():
        raise GmailError("Read access to the mailbox wasn't granted")
    if not body.get("refresh_token"):
        raise GmailError("Google gave no lasting access — remove the ERP in the mailbox's Google account settings and connect again")
    return body


class Gmail:
    """Read-only calls on the connected mailbox. GET only — there is no method that changes anything."""

    def __init__(self, refresh_token: str, timeout: float = 60):
        self._refresh = refresh_token
        self._token: Optional[str] = None
        self._exp = 0.0
        self._http = httpx.Client(timeout=timeout)

    def _auth(self) -> dict:
        if not self._token or time.time() > self._exp - 60:
            r = self._http.post(TOKEN_URI, data={"client_id": client_id(), "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
                                                 "refresh_token": self._refresh, "grant_type": "refresh_token"})
            if r.status_code != 200:
                raise GmailError("The mailbox connection has expired or was removed — connect it again in Settings")
            b = r.json()
            self._token, self._exp = b["access_token"], time.time() + b.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, **params) -> dict:
        r = self._http.get(f"{API}{path}", params=params, headers=self._auth())
        if r.status_code == 404 and path == "/history":
            raise HistoryGone()
        if r.status_code == 429 or (r.status_code == 403 and any(w in r.text for w in ("Quota exceeded", "rateLimitExceeded", "userRateLimitExceeded"))):
            raise RateLimited()
        if r.status_code >= 400:
            raise GmailError(f"Gmail {r.status_code}: {r.text[:200]}")
        return r.json()

    def watch(self, topic: str) -> dict:
        # users.watch is a POST but changes nothing in the mailbox: it asks Gmail to notify Pub/Sub of new mail
        r = self._http.post(f"{API}/watch", headers=self._auth(), json={"topicName": topic, "labelIds": ["INBOX"],
                                                                       "labelFilterBehavior": "include"})
        if r.status_code >= 400:
            raise GmailError(f"Gmail watch {r.status_code}: {r.text[:200]}")
        return r.json()

    def profile(self) -> dict:
        return self._get("/profile")

    def new_ids(self, start: str) -> tuple[list[str], str]:
        """Message ids added since history id `start` (oldest first) and the newest history id."""
        ids, latest, page = [], start, None
        while True:
            b = self._get("/history", startHistoryId=start, historyTypes="messageAdded", maxResults=500,
                          **({"pageToken": page} if page else {}))
            latest = b.get("historyId", latest)
            for h in b.get("history", []):
                for a in h.get("messagesAdded", []):
                    ids.append(a["message"]["id"])
            page = b.get("nextPageToken")
            if not page:
                return list(dict.fromkeys(ids)), latest

    def search(self, q: str, limit: int = 500) -> list[str]:
        ids, page = [], None
        while len(ids) < limit:
            b = self._get("/messages", q=q, maxResults=100, **({"pageToken": page} if page else {}))
            ids += [m["id"] for m in b.get("messages", [])]
            page = b.get("nextPageToken")
            if not page:
                break
        return list(reversed(ids))  # Gmail lists newest first

    def raw(self, msg_id: str) -> bytes:
        b = self._get(f"/messages/{msg_id}", format="raw")
        return base64.urlsafe_b64decode(b["raw"] + "=" * (-len(b["raw"]) % 4))


class RateLimited(GmailError):
    """Gmail's per-minute limit for one mailbox — stop now, carry on at the next check."""


class HistoryGone(GmailError):
    """The saved history id is too old (Gmail keeps about a week) — fall back to a search."""


def reader(st: dict) -> Optional[Gmail]:
    if not st.get("token"):
        return None
    return Gmail(_fernet().decrypt(st["token"].encode()).decode())


def connect(db: Session, body: dict) -> dict:
    """Store the new connection and start from 'now' (plus the last 30 days of ICEGATE mails)."""
    row, st = state(db)
    g = Gmail(body["refresh_token"])
    prof = g.profile()
    st = {"mailbox": prof.get("emailAddress"), "token": _fernet().encrypt(body["refresh_token"].encode()).decode(),
          "history_id": None, "connected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    save(db, row, st)
    return st


def sync(db: Session, gm: Optional[Gmail] = None, topic: Optional[str] = None) -> dict:
    """Read every mail added since the last run and import it. Safe to call often (push + 15-min job)."""
    from app.icegate_mail.apply import import_mails
    from app.models.user import User
    from app.core.enums import UserRole

    from cryptography.fernet import InvalidToken

    row, st = state(db)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if gm is None:
        try:
            gm = reader(st)
        except (GmailError, InvalidToken):
            st.update(last_run=now, last_error="The mailbox connection can't be opened (encryption key changed?) — connect it again")
            save(db, row, st)
            return st
    if gm is None:
        return st
    try:
        # the list of mails still to read is kept, so a limit hit or a timeout never starts over
        if not st.get("queue"):
            if st.get("history_id"):
                try:
                    ids, latest = gm.new_ids(st["history_id"])
                except HistoryGone:
                    ids, latest = gm.search(f"{QUERY} newer_than:10d"), gm.profile()["historyId"]
            else:  # first run: the last 30 days (at most FIRST_LIMIT mails)
                latest = gm.profile()["historyId"]
                ids = gm.search(f"{QUERY} newer_than:30d", limit=FIRST_LIMIT)
            st.update(queue=ids, pending_history=str(latest))
            save(db, row, st)
        # documents from mail are added in the admin's name (the only admin, client 2026-09-29)
        admin = db.query(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).order_by(User.id).first()
        new = 0
        started = time.time()
        while st.get("queue"):
            if time.time() - started > RUN_SECONDS:
                break  # the rest at the next check
            msg_id = st["queue"][0]
            raw = gm.raw(msg_id)
            new += import_mails(db, [raw], admin).get("new", 0)
            row, st = state(db)  # the import committed
            st["queue"] = st["queue"][1:]
            save(db, row, st)
            time.sleep(PACE)  # well under Gmail's per-minute limit
        row, st = state(db)
        st.update(last_run=now, last_error=None, last_new=new, paused=None)
        if not st.get("queue"):
            st["history_id"] = st.pop("pending_history", None) or st.get("history_id")
        if topic and (not st.get("watch_expires") or int(st["watch_expires"]) / 1000 - time.time() < 2 * 86400):
            try:
                w = gm.watch(topic)
                st["watch_expires"], st["push_error"] = w.get("expiration"), None
            except GmailError as e:  # push not allowed (e.g. org policy on the topic): the 15-min check still reads
                st["push_error"] = str(e)[:200]
    except RateLimited:
        db.rollback()
        row, st = state(db)
        left = len(st.get("queue") or [])
        st.update(last_run=now, last_error=None,
                  paused=f"Gmail asked the ERP to slow down — {left} mail(s) left, read at the next check" if left else None)
    except (GmailError, httpx.HTTPError, KeyError, ValueError) as e:
        db.rollback()
        row, st = state(db)
        st.update(last_run=now, last_error=str(e)[:300])
    save(db, row, st)
    return st


def topic_name() -> Optional[str]:
    return os.getenv("GMAIL_PUBSUB_TOPIC") or None  # projects/<project>/topics/icegate-mail


def run_job() -> None:
    """Every 15 min (safety net) and on every push. Also renews the Gmail watch (it lapses after 7 days)."""
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        sync(db, topic=topic_name())

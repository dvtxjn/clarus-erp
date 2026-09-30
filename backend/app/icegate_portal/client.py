"""
The ICEGATE portal (foservices.icegate.gov.in), logged in as the office's ICEGATE ID — read-only lookups
(client, 2026-09-30). Mapped from the portal's own web app, calls verified in a logged-in session:

  login     POST identity/ext-login {icegateId, password (the portal's AES-ECB with its built-in key), usertype}
            -> {sessionId, token, email, mobile, approvedRoles, ...}; an OTP is mailed (otp/Ext/otp/{id}),
            read by the ICEGATE mailbox reader, then POST otp/Ext/verify-otp/{id} {otp, otpType "L"}.
  keep      POST identity/refresh-token {icegateId, sessionId} (header Authorization) — the web page logs out
            when idle; one session is kept alive between runs so an OTP is only needed when it lapses.
  headers   Authorization: <token>, session_id: <sessionId>, channel: browser, Accept-Language: en-US
  BE status POST enquiry/enquiryatices/BETrack_Ices_action_Internal
            {icegateId, roleId, location, beNo, beDt yyyymmdd, licenseNo <CHA licence>, externalFlag true}
  queries   POST enquiry/docenquiry/BeQueryReply {icegateId, roleId, code <CHA licence>}  (last ~15 days)
  challans  POST dashboard/challansGenerated/getChallanDetailsForCB/ {iecCode, icegateId, roleId, startDate, endDate}
            with nulls = every pending challan (the page's "items per page" only limits the display)

Nothing here files, replies, pays or changes anything on ICEGATE. The login and OTP steps follow the portal's
code and have not been run yet. The password resets periodically (client): it's entered in the ERP by the admin
or an import manager, kept encrypted, and a refused password stops all logins until a new one is entered (so the
account never gets locked by repeated tries).
"""
from __future__ import annotations

import base64
import os
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

import httpx

BASE = "https://foservices.icegate.gov.in"
PORTAL_KEY = "aWNlZ2F0ZWNiaWNkZWxoaQ=="  # the portal's own login-encryption key (public, in its web app)
ROLE_CB = 3                                # Customs Broker


class PortalError(Exception):
    pass


class SessionLapsed(PortalError):
    """The saved session is no longer accepted — log in again (needs a fresh OTP)."""


def encrypt_password(pw: str) -> str:
    """What the portal's login page does to the password before sending it."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = base64.b64decode(PORTAL_KEY)
    p = padding.PKCS7(128).padder()
    data = p.update(pw.encode()) + p.finalize()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode()


class BadPassword(PortalError):
    """ICEGATE refused the ID / password — it resets periodically (client): stop until someone enters the new one."""


class Portal:
    def __init__(self, cfg: dict, session: Optional[dict] = None, timeout: float = 60, http: Optional[httpx.Client] = None):
        self.cfg = cfg  # {icegate_id, password, cha_code, role_id} — from the ERP (sync.credentials)
        self.session = dict(session or {})  # {token, sessionId, at}
        self._http = http or httpx.Client(base_url=BASE, timeout=timeout,
                                          headers={"Accept-Language": "en-US", "channel": "browser",
                                                   "Content-Type": "application/json"})

    # --- session ---
    def _headers(self) -> dict:
        h = {}
        if self.session.get("token"):
            h["Authorization"] = self.session["token"]
        if self.session.get("sessionId"):
            h["session_id"] = self.session["sessionId"]
        return h

    def login(self, wait_for_otp: Callable[[datetime], Optional[str]]) -> dict:
        """Full login: password -> OTP (mailed; wait_for_otp reads it from the mailbox) -> verify."""
        c = self.cfg
        if not (c.get("icegate_id") and c.get("password") and c.get("cha_code")):
            raise PortalError("ICEGATE login isn't set up — enter the ICEGATE ID, CHA code and password on the Customs mail page")
        started = datetime.now(timezone.utc)
        r = self._http.post("/identity/ext-login", json={"icegateId": c["icegate_id"],
                                                         "password": encrypt_password(c["password"]), "usertype": "external"})
        if r.status_code != 200:
            msg = _err(r)
            if r.status_code in (400, 401, 403) and any(w in msg.lower() for w in ("password", "credential", "invalid", "incorrect", "wrong")):
                raise BadPassword(f"ICEGATE didn't accept the password ({msg})")
            raise PortalError(f"ICEGATE refused the login ({r.status_code}): {msg}")
        b = r.json()
        sid, token = b.get("sessionId"), b.get("token")
        if not sid:
            raise PortalError("ICEGATE's login answer had no session")
        # ask for the OTP (the page does this right after the password)
        self._http.post(f"/otp/Ext/otp/{c['icegate_id']}", json={"email": b.get("email"), "mobile": b.get("mobile") or b.get("mobileNo"),
                                                                 "otpType": "L"}, headers={"Session_id": sid})
        otp = wait_for_otp(started)
        if not otp:
            raise PortalError("No ICEGATE OTP arrived in the mailbox within 3 minutes")
        v = self._http.post(f"/otp/Ext/verify-otp/{c['icegate_id']}", json={"otp": otp, "otpType": "L"},
                            headers={"session_id": sid, "Session_id": sid})
        if v.status_code != 200:
            raise PortalError(f"ICEGATE didn't accept the OTP ({v.status_code}): {_err(v)}")
        vb = v.json() if v.content else {}
        self.session = {"token": vb.get("token") or token, "sessionId": sid,
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return self.session

    def keep_alive(self) -> None:
        """Refresh the saved session; SessionLapsed if ICEGATE no longer accepts it."""
        if not self.session.get("token"):
            raise SessionLapsed("no session")
        r = self._http.post("/identity/refresh-token", json={"icegateId": self.cfg["icegate_id"],
                                                             "sessionId": self.session.get("sessionId")},
                            headers={"Authorization": self.session["token"]})
        if r.status_code in (401, 403) or (r.status_code == 400 and "auth" in r.text.lower()):
            raise SessionLapsed("ICEGATE session ended")
        if r.status_code == 200 and r.content:
            b = r.json()
            if isinstance(b, dict) and b.get("token"):
                self.session["token"] = b["token"]

    def logout(self) -> None:
        try:
            self._http.post("/identity/userLogout/logout", json={"icegateId": self.cfg["icegate_id"],
                                                                 "sessionId": self.session.get("sessionId"), "roleId": self.cfg["role_id"]},
                            headers=self._headers())
        except httpx.HTTPError:
            pass
        self.session = {}

    def _post(self, path: str, body: dict):
        r = self._http.post(path, json=body, headers=self._headers())
        if r.status_code in (401, 403) or "auth error" in r.text.lower():
            raise SessionLapsed("ICEGATE session ended")
        if r.status_code == 400 and "no details found" in r.text.lower():
            return []
        if r.status_code >= 400:
            raise PortalError(f"ICEGATE {path.rsplit('/', 2)[-2] if path.endswith('/') else path.rsplit('/', 1)[-1]}: "
                              f"{r.status_code} {_err(r)}")
        return r.json() if r.content else None

    # --- lookups (read-only) ---
    def be_status(self, port: str, be_no: str, be_date: date) -> Optional[dict]:
        c = self.cfg
        try:
            return self._post("/enquiry/enquiryatices/BETrack_Ices_action_Internal",
                              {"icegateId": c["icegate_id"], "roleId": c["role_id"], "location": port, "beNo": str(be_no),
                               "beDt": be_date.strftime("%Y%m%d"), "licenseNo": c["cha_code"], "externalFlag": True})
        except PortalError as e:
            if "does not belong" in str(e).lower():
                return None  # not our BE on that date (numbers are reused every year)
            raise

    def queries(self) -> list[dict]:
        c = self.cfg
        return self._post("/enquiry/docenquiry/BeQueryReply", {"icegateId": c["icegate_id"], "roleId": c["role_id"],
                                                               "code": c["cha_code"]}) or []

    def challans(self) -> list[dict]:
        c = self.cfg
        return self._post("/dashboard/challansGenerated/getChallanDetailsForCB/",
                          {"iecCode": None, "icegateId": c["icegate_id"], "roleId": c["role_id"], "startDate": None,
                           "endDate": None}) or []


def _err(r: httpx.Response) -> str:
    try:
        b = r.json()
        return "; ".join(b.get("errors") or []) or b.get("message") or r.text[:150]
    except (ValueError, AttributeError):
        return r.text[:150]


# --- parsing ICEGATE's values ---
def na(v):
    return None if v in (None, "", "N.A.", "NA", "-") else v


def ts(v) -> Optional[datetime]:
    """'2026-09-29 20:50:09.0' (India time) -> aware datetime."""
    v = na(v)
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        except ValueError:
            pass
    return None


def day(v) -> Optional[date]:
    v = na(v)
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(v)[:10], fmt).date()
        except ValueError:
            pass
    return None


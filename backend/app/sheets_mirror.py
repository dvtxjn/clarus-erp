"""
View-only copy of the tracker in Google Sheets (client, 2026-09-30, P0): if the ERP is ever down, the
office still sees every live shipment. Written every 15 minutes by the ERP's service account.

- The admin makes the sheet, shares it with the service account as Editor (everyone else: Viewer only),
  and pastes its link in Settings. The ERP writes to that one spreadsheet and nothing else.
- Never deletes: rows that are no longer live are blanked by writing empty cells over them; a missing
  tab is added, never removed. Requests that delete anything are refused before they are sent.
- No invoice / billing figures go to the sheet (invoicing is admin-only).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from jose import jwt
from sqlalchemy.orm import Session

from app.models.settings import AppSetting

API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TAB = "Tracker"
KEY = "sheets_mirror"  # app_settings: {"sheet_id", "last_run", "last_error", "rows", "cols"}

# (header, shipment attribute) — the tracker's working columns; no invoice amounts
COLUMNS: list[tuple[str, str]] = [
    ("Client", "client"), ("Job", "job"), ("Consignee", "consignee"), ("MBL", "mbl"), ("HBL", "hbl"),
    ("BE No", "be_no"), ("BE Date", "be_dt"), ("Description", "be_description"), ("Port", "port"),
    ("POD", "pod"), ("ETA", "eta"), ("INW", "inw"), ("Day", "day"), ("Licence", "license"),
    ("Container", "container"), ("Cont", "cont"), ("Gross Wt", "gross_wt"), ("CFS", "cfs"),
    ("Container Status", "container_status"), ("Shipping Line", "shipping_line"), ("IGM", "igm"),
    ("IGM Date", "igm_date"), ("Line No", "line_no"), ("Status", "status"), ("Duty Paid", "duty_paid"),
    ("CFS Inv Received", "cfs_inv_received"), ("Line Paid", "line_paid"), ("OOC", "ooc"), ("DO", "do"),
    ("OOC Date", "ooc_date"), ("Cleared Date", "cleared_date"), ("Delivery Status", "delivery_status"),
    ("Remark", "remark"), ("Remarks", "remarks"), ("Stuck", "is_stuck"),
]


class SheetsError(Exception):
    pass


def sheet_id_from(link: str) -> Optional[str]:
    """The spreadsheet id from a pasted link (or the bare id)."""
    link = (link or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", link)
    if m:
        return m.group(1)
    return link if re.fullmatch(r"[A-Za-z0-9_-]{20,}", link) else None


class SheetsClient:
    """Writes to ONE spreadsheet. No delete of any kind."""

    def __init__(self, sheet_id: str, service_account: Optional[dict] = None, timeout: float = 60):
        self.sheet_id = sheet_id
        self._sa = service_account
        self._token: Optional[str] = None
        self._exp = 0.0
        self._http = httpx.Client(timeout=timeout)

    def _auth(self) -> dict:
        if not self._token or time.time() > self._exp - 60:
            from app.storage.drive_client import load_service_account

            sa = self._sa or load_service_account()
            now = int(time.time())
            uri = sa.get("token_uri", "https://oauth2.googleapis.com/token")
            assertion = jwt.encode({"iss": sa["client_email"], "scope": SCOPE, "aud": uri, "iat": now, "exp": now + 3600},
                                   sa["private_key"], algorithm="RS256")
            r = self._http.post(uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
            if r.status_code != 200:
                raise SheetsError(f"Google login for the service account failed ({r.status_code})")
            body = r.json()
            self._token, self._exp = body["access_token"], time.time() + body.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}"}

    def _req(self, method: str, path: str, **kw) -> dict:
        body = json.dumps(kw.get("json") or {})
        if method.upper() == "DELETE" or re.search(r'"delete\w*"', body, re.I) or ":clear" in path:
            raise SheetsError("Refused: the ERP never deletes anything in Google Sheets")
        r = self._http.request(method, f"{API}/{self.sheet_id}{path}", headers=self._auth(), **kw)
        if r.status_code == 403:
            raise SheetsError("The ERP can't edit this sheet — share it with the ERP's Google account as Editor")
        if r.status_code == 404:
            raise SheetsError("Sheet not found — check the link")
        if r.status_code >= 400:
            raise SheetsError(f"Google Sheets {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else {}

    def ensure_tab(self, title: str) -> None:
        meta = self._req("GET", "", params={"fields": "sheets.properties.title"})
        if title not in [s["properties"]["title"] for s in meta.get("sheets", [])]:
            self._req("POST", ":batchUpdate", json={"requests": [{"addSheet": {"properties": {"title": title}}}]})

    def write(self, rng: str, rows: list[list]) -> None:
        self._req("PUT", f"/values/{rng}", params={"valueInputOption": "RAW"}, json={"range": rng, "values": rows})


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "✓" if v else ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%d/%m/%Y")
    if hasattr(v, "value"):  # enum
        return str(v.value).replace("_", " ").upper()
    return str(v)


def build_rows(db: Session) -> list[list[str]]:
    """Header + one row per live (not archived, not deleted) shipment, by client then job. Custom tracker
    columns are added at the end."""
    from app.models.shipment import Shipment
    from app.models.tracker_column import TrackerColumn

    removed = {c.key for c in db.query(TrackerColumn).filter(TrackerColumn.is_removed.is_(True))}
    cols = [c for c in COLUMNS if c[1] not in removed]
    custom = db.query(TrackerColumn).filter(TrackerColumn.is_custom.is_(True), TrackerColumn.is_removed.is_(False)).all()
    q = db.query(Shipment).filter(Shipment.is_archived.is_(False))
    if hasattr(Shipment, "deleted_at"):
        q = q.filter(Shipment.deleted_at.is_(None))
    ships = sorted(q.all(), key=lambda s: ((s.client or "").lower(), s.job or ""))
    rows = [[h for h, _ in cols] + [c.label for c in custom]]
    for s in ships:
        cf = s.custom_fields or {}
        rows.append([_cell(getattr(s, a)) for _, a in cols] + [_cell(cf.get(c.key)) for c in custom])
    return rows


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _state(db: Session) -> tuple[AppSetting, dict]:
    row = db.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value={})
        db.add(row)
    return row, dict(row.value or {})


def mirror(db: Session, client: Optional[SheetsClient] = None) -> dict:
    """Write the tracker to the sheet now. Returns the saved state (with last_error on failure)."""
    row, st = _state(db)
    if not st.get("sheet_id"):
        return st
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        c = client or SheetsClient(st["sheet_id"])
        data = build_rows(db)
        width = max(len(data[0]), st.get("cols") or 0)
        height = max(len(data), st.get("rows") or 0)  # blank out rows left over from last time
        grid = [r + [""] * (width - len(r)) for r in data] + [[""] * width for _ in range(height - len(data))]
        c.ensure_tab(TAB)
        c.write(f"{TAB}!A1:{_col(width)}{height}", grid)
        c.ensure_tab("About")
        c.write("About!A1:B3", [["Copy of the Clarus ERP tracker — view only. Changes here are overwritten.", ""],
                                ["Last updated (UTC)", now], ["Live shipments", str(len(data) - 1)]])
        st.update(last_run=now, last_error=None, rows=len(data), cols=len(data[0]))
    except (SheetsError, httpx.HTTPError, KeyError, ValueError) as e:
        st.update(last_run=now, last_error=str(e)[:300])
    row.value = st
    db.commit()
    return st


def run_job() -> None:
    """Every 15 minutes (Cloud Scheduler -> /internal/jobs/sheets-mirror)."""
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        mirror(db)

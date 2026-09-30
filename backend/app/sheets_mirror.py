"""
View-only copy of the tracker in Google Sheets (client, 2026-09-30, P0): if the ERP is ever down, the
office still sees every live shipment. Written every 15 minutes by the ERP's service account.

- The admin makes the sheet, shares it with the service account as Editor (everyone else: Viewer only),
  and pastes its link in Settings. The ERP writes to that one spreadsheet and nothing else.
- Never deletes: rows that are no longer live are blanked by writing empty cells over them; a missing
  tab is added, never removed. Requests that delete anything are refused before they are sent.
- No invoice / billing figures go to the sheet (invoicing is admin-only).
- Laid out like the office's own Google Sheets tracker (client, 2026-09-30): same columns and order, frozen
  Job / MBL, dark green header with filters, rows by client, tick boxes for Duty / CFS Inv / Line / OOC / DO,
  coloured POD, HSS consignee in green, Cleared Date in bold.
- With the office sheet's own rules (read from it, 2026-09-30): dates are real dates (dd-Mmm-yyyy), the
  Yes/No columns are tick boxes that hold "Yes" / "No", and "day" is the sheet's own formula counting
  from the INW (INW = day 1, "Pending" until there is one) — so the copy keeps working like the tracker.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from jose import jwt
from sqlalchemy.orm import Session

from app.models.settings import AppSetting

API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TAB = "Tracker"
KEY = "sheets_mirror"  # app_settings: {"sheet_id", "last_run", "last_error", "rows", "cols"}

GREEN_HEAD = {"red": 0.24, "green": 0.42, "blue": 0.31}
WHITE = {"red": 1, "green": 1, "blue": 1}
POD_COLOURS = {  # like the office tracker's POD chips
    "INMUN1": ({"red": 0.85, "green": 0.92, "blue": 0.83}, None),
    "INNSA1": ({"red": 0.81, "green": 0.89, "blue": 0.96}, None),
    "INDWN6": ({"red": 0.07, "green": 0.33, "blue": 0.63}, WHITE),
}
HSS_GREEN = {"red": 0.72, "green": 0.88, "blue": 0.73}


def _inw(v):
    """The INW is free text in the ERP ('Pending', '19-Sep-2026'): a real date when it reads as one."""
    from app.alerts import parse_inw

    return parse_inw(v) or (v or "")


# the office sheet's "day" formula, word for word; {inw} = the INW cell of the same row
DAY_FORMULA = ('=IF({inw}="","Pending",IF(ISNUMBER({inw}),LET(d,{inw},diff,TODAY()-d,adj,IF(diff>=0,diff+1,diff),'
               'adj & IF(ABS(adj)=1," day"," days")),"Pending"))')
SHEETS_EPOCH = date(1899, 12, 30)


def _mbl(s) -> str:
    """As the sheet writes it: MBL/HBL, then the FTA number."""
    out = s.mbl or ""
    if s.hbl:
        out += f"/{s.hbl}"
    if s.fta_info:
        out += f"-{s.fta_info}"
    return out


# (header, value, kind) in the office tracker's order. kind: text | check | date | cleared | pod | consignee
COLUMNS: list[tuple[str, object, str]] = [
    ("Job", lambda s: s.job or "", "text"), ("mbl", _mbl, "text"), ("be description", lambda s: s.be_description or "", "text"),
    ("eta", lambda s: s.eta, "date"), ("inw", lambda s: _inw(s.inw), "date"), ("day", lambda s: "", "day"),
    ("License", lambda s: s.license or "", "text"), ("client", lambda s: s.client or "", "text"),
    ("consignee", lambda s: s.consignee or "", "consignee"), ("pod", lambda s: s.pod or s.port or "", "pod"),
    ("cntr status", lambda s: s.container_status or "", "text"), ("cfs", lambda s: s.cfs or "", "text"),
    ("be no", lambda s: s.be_no or "", "text"), ("be dt", lambda s: s.be_dt, "date"),
    ("cntr", lambda s: s.container or "", "text"), ("gross wt", lambda s: s.gross_wt or "", "text"),
    ("remark", lambda s: s.remark or "", "text"), ("POC", lambda s: s.poc or "", "text"),
    ("remarks", lambda s: s.remarks or "", "text"), ("Cleared Date", lambda s: s.cleared_date, "cleared"),
    ("duty paid?", lambda s: bool(s.duty_paid), "check"), ("cfs inv?", lambda s: bool(s.cfs_inv_received), "check"),
    ("line paid?", lambda s: bool(s.line_paid), "check"), ("ooc?", lambda s: bool(s.ooc), "check"),
    ("do?", lambda s: bool(s.do), "check"), ("igm", lambda s: s.igm or "", "text"),
    ("Delivery", lambda s: s.delivery_status or "", "text"),
]
FIELD_OF = {"be description": "be_description", "cntr status": "container_status", "cntr": "container",
            "gross wt": "gross_wt", "poc": "poc", "cleared date": "cleared_date", "delivery": "delivery_status"}


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

    def ensure_tab(self, title: str) -> int:
        """The tab's sheetId (added when missing)."""
        meta = self._req("GET", "", params={"fields": "sheets.properties(title,sheetId)"})
        for sh in meta.get("sheets", []):
            if sh["properties"]["title"] == title:
                return sh["properties"]["sheetId"]
        r = self._req("POST", ":batchUpdate", json={"requests": [{"addSheet": {"properties": {"title": title}}}]})
        return r["replies"][0]["addSheet"]["properties"]["sheetId"]

    def batch(self, requests: list[dict]) -> None:
        self._req("POST", ":batchUpdate", json={"requests": requests})

    def write(self, rng: str, rows: list[list]) -> None:
        self._req("PUT", f"/values/{rng}", params={"valueInputOption": "RAW"}, json={"range": rng, "values": rows})


def build_rows(db: Session) -> tuple[list[str], list[list[tuple]]]:
    """(headers, rows) — every live (not archived, not deleted) shipment, grouped by client, then by ETA
    (like the office tracker). Each cell is (value, kind, shipment). Custom tracker columns go at the end."""
    from app.models.shipment import Shipment
    from app.models.tracker_column import TrackerColumn

    removed = {c.key for c in db.query(TrackerColumn).filter(TrackerColumn.is_removed.is_(True))}
    cols = [c for c in COLUMNS if FIELD_OF.get(c[0].lower(), c[0].lower()) not in removed]
    custom = db.query(TrackerColumn).filter(TrackerColumn.is_custom.is_(True), TrackerColumn.is_removed.is_(False)).all()
    ships = db.query(Shipment).filter(Shipment.is_archived.is_(False)).all()
    ships.sort(key=lambda s: ((s.client or "~").lower(), s.eta or date.max, s.job or ""))
    headers = [h for h, _, _ in cols] + [c.label for c in custom]
    rows = []
    for s in ships:
        cf = s.custom_fields or {}
        rows.append([(fn(s), kind, s) for _, fn, kind in cols] + [("" if cf.get(c.key) is None else str(cf.get(c.key)), "text", s) for c in custom])
    return headers, rows


def _cell(value, kind: str, s=None, inw_ref: Optional[str] = None) -> dict:
    """One Google Sheets cell: value + look (+ a tick box for the Yes/No columns). inw_ref = this row's INW
    cell (e.g. "E7") for the day formula."""
    fmt: dict = {"verticalAlignment": "MIDDLE", "textFormat": {"fontSize": 10}}
    cell: dict = {}
    if kind == "check":
        # the office sheet's tick boxes hold "Yes" / "No"
        cell["userEnteredValue"] = {"stringValue": "Yes" if value else "No"}
        cell["dataValidation"] = {"condition": {"type": "BOOLEAN", "values": [{"userEnteredValue": "Yes"},
                                                                              {"userEnteredValue": "No"}]}}
        fmt["horizontalAlignment"] = "CENTER"
    elif kind == "day":
        cell["userEnteredValue"] = {"formulaValue": DAY_FORMULA.format(inw=inw_ref)} if inw_ref else {"stringValue": ""}
        fmt["horizontalAlignment"] = "CENTER"
    elif isinstance(value, date):
        cell["userEnteredValue"] = {"numberValue": (value - SHEETS_EPOCH).days}
        fmt["numberFormat"] = {"type": "DATE", "pattern": "dd-mmm-yyyy"}
    else:
        cell["userEnteredValue"] = {"stringValue": str(value or "")}
    if kind == "cleared":
        fmt["textFormat"]["bold"] = True
    if kind == "pod":
        code = (getattr(s, "port", None) or str(value)[:6]).upper()
        if code in POD_COLOURS:
            bg, fg = POD_COLOURS[code]
            fmt["backgroundColor"] = bg
            if fg:
                fmt["textFormat"]["foregroundColor"] = fg
    if kind == "consignee" and s is not None and getattr(s, "is_hss", False):
        fmt["backgroundColor"] = HSS_GREEN
    if kind in ("date", "cleared"):
        fmt["horizontalAlignment"] = "CENTER"
    cell["userEnteredFormat"] = fmt
    return cell


def _header_cell(title: str) -> dict:
    return {"userEnteredValue": {"stringValue": title},
            "userEnteredFormat": {"backgroundColor": GREEN_HEAD, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                                  "wrapStrategy": "WRAP", "textFormat": {"bold": True, "foregroundColor": WHITE, "fontSize": 10}}}


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
        db.flush()  # a second lookup in the same session finds it
    return row, dict(row.value or {})


def mirror(db: Session, client: Optional[SheetsClient] = None) -> dict:
    """Write the tracker to the sheet now. Returns the saved state (with last_error on failure)."""
    row, st = _state(db)
    if not st.get("sheet_id"):
        return st
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        c = client or SheetsClient(st["sheet_id"])
        headers, rows = build_rows(db)
        width = max(len(headers), st.get("cols") or 0)
        height = max(len(rows) + 1, st.get("rows") or 0)  # rows left over from last time are blanked
        grid = [{"values": [_header_cell(h) for h in headers] + [{} for _ in range(width - len(headers))]}]
        inw_col = _col(headers.index("inw") + 1) if "inw" in headers else None
        for n, r in enumerate(rows, start=2):
            ref = f"{inw_col}{n}" if inw_col else None
            grid.append({"values": [_cell(v, k, s, ref) for v, k, s in r] + [{} for _ in range(width - len(r))]})
        grid += [{"values": [{} for _ in range(width)]} for _ in range(height - len(grid))]
        gid = c.ensure_tab(TAB)
        c.batch([
            {"updateCells": {"range": {"sheetId": gid, "startRowIndex": 0, "startColumnIndex": 0,
                                       "endRowIndex": height, "endColumnIndex": width},
                             "rows": grid, "fields": "userEnteredValue,userEnteredFormat,dataValidation"}},
            {"updateSheetProperties": {"properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
                                       "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
            {"setBasicFilter": {"filter": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": len(rows) + 1,
                                                     "startColumnIndex": 0, "endColumnIndex": len(headers)}}}},
        ])
        c.ensure_tab("About")
        c.write("About!A1:B3", [["Copy of the Clarus ERP tracker — view only. Changes here are overwritten.", ""],
                                ["Last updated (India time)", datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%b-%Y %H:%M")],
                                ["Live shipments", str(len(rows))]])
        st.update(last_run=now, last_error=None, rows=len(rows) + 1, cols=len(headers))
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

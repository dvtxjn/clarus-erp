"""
Re-import the Google Sheets tracker CSV so the app picks up where the sheet is
(client, 2026-09-28). Preview first, then apply.

Rules
  - The updated sheet wins over edits made in the app ...
  - ... except data read from a Bill of Entry: when a shipment has an uploaded
    Assessed / OOC BE, its BE No, BE Date, port, MBL, HBL, containers and gross weight
    are kept ("kept from BE"); with an OOC copy, OOC / Duty Paid stay ticked.
  - App-only data is never touched (documents, proformas, invoices, challans, HSS
    parties set by hand, paid-by-us switches, amounts).
  - Shipments not in the CSV are flagged (Shipment.missing_from_sheet_at), never deleted —
    except cleared / billed ones: those have moved to the monthly FNF sheets (client, 2026-10-07).
  - IGM details (MBL/HBL date, GW, packages, line no, IGM date, voyage, cont) come from the
    IGM lookup in the app: a blank cell keeps them (the sheet no longer fills those columns).
  - A row matching a shipment deleted in the app is skipped (not re-created): the admin
    restores it from Recently deleted if the delete was a mistake.
  - Matching: MBL, then HBL, then BE No, then Job No; the last two are marked
    "check" in the preview. An "MBL/HBL" cell is split at the "/" (or an HBL column is used).
  - Status follows the evidence rules (status_rules); "billed?" Yes bills the shipment,
    an explicit No un-bills it (status restored from the evidence); blank leaves billing alone.
  - Every change is audit-logged; unknown columns are reported.
  - An .xlsx of the whole tracker is read too: the TRACKER tab plus the monthly "FnF" tabs
    (cleared shipments). FnF rows only update shipments already in the app — older jobs
    that never were in the app are not created (client, 2026-10-07). Other tabs are ignored.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.enums import DocumentType, ShipmentStatus
from app.core.status_rules import EVIDENCE_FIELDS, proven_status, status_after_evidence_change
from app.import_tracker_csv import _clean, _date, _name, _normalize_headers, _yes
from app.models.document import HSCode, ShipmentDocument
from app.models.shipment import Shipment
from app.seed import TYRE_HS_CODE

# sheet column -> (field, parser)
COLUMNS: dict[str, tuple[str, Any]] = {
    "job": ("job", lambda v: _clean(v) or ""),
    "be description": ("be_description", _clean), "eta": ("eta", _date), "inw": ("inw", _clean),
    "license": ("license", _clean), "client": ("client", _name), "consignee": ("consignee", _name),
    "pod": ("pod", _clean), "cntr status": ("container_status", _clean), "cfs": ("cfs", _clean),
    "be no": ("be_no", _clean), "be dt": ("be_dt", _date), "cntr": ("container", _clean),
    "gross wt": ("gross_wt", _clean), "remark": ("remark", _clean), "poc": ("poc", _clean),
    "remarks": ("remarks", _clean), "cleared date": ("cleared_date", _date),
    "duty paid?": ("duty_paid", _yes), "cfs inv?": ("cfs_inv_received", _yes), "line paid?": ("line_paid", _yes),
    "ooc?": ("ooc", _yes), "do?": ("do", _yes), "igm": ("igm", _clean), "delivery": ("delivery_status", _clean),
    "mbl date": ("mbl_date", _date), "hbl date": ("hbl_date", _date), "gw": ("gw", _clean),
    "total pkg": ("total_pkg", _clean), "pkg code": ("pkg_code", _clean), "line no": ("line_no", _clean),
    "igm date": ("igm_date", _date), "voyage": ("voyage", _clean), "cont": ("cont", _clean),
    "line": ("shipping_line", _clean),
}
SPECIAL = {"mbl", "hbl", "billed?", "day", "status"}  # handled separately / computed by the app
FROM_BE = {"be_no", "be_dt", "port", "mbl", "hbl", "container", "gross_wt"}
FROM_OOC = {"ooc", "duty_paid"}
IGM_DETAILS = {"mbl_date", "hbl_date", "gw", "total_pkg", "pkg_code", "line_no", "igm_date", "voyage", "cont"}
LABELS = {"container_status": "Cntr Status", "cfs_inv_received": "CFS Inv?", "delivery_status": "Delivery",
          "shipping_line": "Line", "be_dt": "BE Dt", "be_no": "BE No", "is_billed": "Billed?"}


def _key(v: Optional[str]) -> str:
    return re.sub(r"\s+", "", v or "").upper()


def mbl_keys(v: Optional[str]) -> set[str]:
    """Every spelling of one MBL the sheet may use: HMM MBLs are typed with or without the carrier's
    'HDMU' prefix (BHMA05154200 = HDMUBHMA05154200 — client, 2026-09-30), so both match the same shipment."""
    k = _key(v)
    if not k:
        return set()
    out = {k}
    if k.startswith("HDMUBHMA"):
        out.add(k[4:])
    elif k.startswith("BHMA"):
        out.add("HDMU" + k)
    return out


def _is_hbl_format(v: Optional[str]) -> bool:
    """A number whose format is a house BL, never an MBL (client's rules in app/liners.py, e.g. CJHR…)."""
    from app import liners

    hit = liners.identify(v)
    return bool(hit and hit.get("note") and "HBL" in hit["note"])


def split_mbl(cell: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'274483845/QDDR2607499' -> ('274483845', 'QDDR2607499')."""
    parts = [p.strip() for p in (_clean(cell) or "").split("/") if p.strip()]
    return (parts[0] if parts else None), ("/".join(parts[1:]) or None)


FTA_NO = re.compile(r"^(?P<mbl>.*?)[\s-]*(?P<fta>[A-Z]{4}-\d{6}-[A-Z0-9]{5,8})\s*$")


def split_fta(mbl: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'LPL1543012-UKIN-160926-E96101' -> ('LPL1543012', 'UKIN-160926-E96101'): an FTA
    certificate no written after the MBL isn't part of it (client, 2026-09-29)."""
    m = FTA_NO.match((mbl or "").strip().upper())
    if not m or not m.group("mbl").strip():
        return mbl, None
    return (mbl or "").strip()[: len(m.group("mbl").strip())], m.group("fta")


def parse_csv(data: bytes) -> tuple[list[dict], list[str], list[str]]:
    """(rows as field dicts, unknown columns, skipped-row notes)."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        headers = _normalize_headers(next(reader))
    except StopIteration:
        return [], [], ["The file is empty."]
    rows, unknown, skipped = [], [], []
    _parse_table(headers, enumerate(reader, start=2), rows, unknown, skipped)
    return rows, unknown, skipped


NUMBER_FORMAT = re.compile(r'^0(?:\.(0+))?\s*"([^"]*)"$')


def _cell(c: Any) -> str:
    """A cell as the sheet shows it (= what its CSV download has): 29-Sep-2026, 267.076 MTS."""
    v = getattr(c, "value", c)
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d-%b-%Y")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        m = NUMBER_FORMAT.match(getattr(c, "number_format", "") or "")
        if m:
            return f"{v:.{len(m.group(1) or '')}f} {m.group(2)}".strip()
        if float(v).is_integer():
            return str(int(v))
    return str(v)


def parse_xlsx(data: bytes) -> tuple[list[dict], list[str], list[str]]:
    """The whole tracker workbook: the TRACKER tab, then every FnF tab (rows marked _fnf)."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        return [], [], ["Couldn't read the .xlsx file."]
    tabs = [ws for ws in wb.worksheets if "tracker" in ws.title.lower()]
    tabs += [ws for ws in wb.worksheets if "fnf" in ws.title.lower()]
    if not tabs:
        return [], [], ["No TRACKER or FnF tab in the workbook."]
    rows, unknown, skipped = [], [], []
    for ws in tabs:
        it = ws.iter_rows()
        try:
            headers = _normalize_headers([_cell(c) for c in next(it)])
        except StopIteration:
            continue
        fnf = "fnf" in ws.title.lower()
        numbered = ((n, [_cell(c) for c in raw]) for n, raw in enumerate(it, start=2))
        _parse_table(headers, numbered, rows, unknown, skipped, tab=ws.title.strip(), fnf=fnf)
    wb.close()
    return rows, unknown, skipped


def _parse_table(headers: list[str], numbered, rows: list[dict], unknown: list[str], skipped: list[str],
                 tab: Optional[str] = None, fnf: bool = False) -> None:
    unknown += [h for h in headers if h and h not in COLUMNS and h not in SPECIAL and h not in unknown]
    where = f"{tab} row" if tab else "Row"
    for n, raw in numbered:
        if not any(c.strip() for c in raw):
            continue
        r = dict(zip(headers, raw + [""] * (len(headers) - len(raw))))
        mbl, hbl = split_mbl(r.get("mbl"))
        mbl, fta = split_fta(mbl)
        if mbl and hbl and _is_hbl_format(mbl) and not _is_hbl_format(hbl):
            mbl, hbl = hbl, mbl  # typed "HBL/MBL" (e.g. CJHRUSF0418/275957617): the HBL went first
        if "hbl" in r and _clean(r["hbl"]):
            hbl = _clean(r["hbl"])
        if not mbl and not hbl:
            if not fnf:  # FnF tabs end with blank / total lines
                skipped.append(f"{where} {n}: no MBL / HBL")
            continue
        fields = {field: parse(r[col]) for col, (field, parse) in COLUMNS.items() if col in r}
        fields["mbl"], fields["hbl"] = mbl or "", hbl
        if fta:  # only when the sheet has one — never blanks an FTA no typed in the app
            fields["fta_info"] = fta
        pod = fields.get("pod")
        m = re.match(r"(IN[A-Z]{3}\d)", (pod or "").upper())
        if m or "pod" in r:
            fields["port"] = m.group(1) if m else None
        billed = (_clean(r.get("billed?")) or "").lower()
        if billed in ("yes", "y", "true", "no", "n", "false"):  # blank = no information: leave billing alone
            fields["is_billed"] = billed in ("yes", "y", "true")
        fields["_row"] = len(rows) + 1 if tab else n  # unique across tabs
        fields["_where"] = f"{where} {n}"
        if fnf:
            fields["_fnf"] = True
        rows.append(fields)


def _norm_value(v: Any) -> Any:
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip() or None
    return v


def _show(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, date):
        return v.strftime("%d-%b-%Y")
    return str(v)


def _has_doc(s: Shipment, *types: DocumentType) -> bool:
    return any(d.document_type in types for d in s.documents)


def plan(db: Session, rows: list[dict], lock: bool = False) -> dict:
    """What an import would do — nothing is written. lock=True (apply): one import at a
    time, and every shipment row locked in id order while the import writes."""
    q = db.query(Shipment).execution_options(include_deleted=True)
    if lock:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext('tracker-import'))"))
        q = q.order_by(Shipment.id).with_for_update().populate_existing()
    ships = q.all()
    by_mbl, by_hbl, by_be, by_job = {}, {}, {}, {}
    for s in ships:
        m, h = split_mbl(s.mbl)
        for k in mbl_keys(m) | mbl_keys(s.mbl):
            by_mbl.setdefault(k, s)
        for k in {_key(s.hbl), _key(h)} - {""}:
            by_hbl.setdefault(k, s)
        if s.be_no:
            by_be.setdefault(_key(s.be_no), []).append(s)
        if s.job:
            by_job.setdefault(_key(s.job), []).append(s)

    new, updated, unchanged, seen, deleted, older = [], [], 0, set(), [], 0
    for r in rows:
        s, how = None, None
        for how_, table, keys in (("MBL", by_mbl, mbl_keys(r["mbl"])), ("HBL", by_hbl, {_key(r.get("hbl"))} - {""}),
                                  ("HBL", by_mbl, mbl_keys(r.get("hbl")))):
            hit = next((table[k] for k in sorted(keys) if k in table and table[k].id not in seen), None)
            if hit is not None:
                s, how = hit, how_
                break
        if s is None:
            for how_, table, k in (("BE No", by_be, _key(r.get("be_no"))), ("Job", by_job, _key(r.get("job")))):
                cands = [x for x in table.get(k, []) if x.id not in seen] if k else []
                if len(cands) == 1:
                    s, how = cands[0], how_
                    break
        if s is None and r.get("_fnf"):
            older += 1  # cleared before the app — not created
            continue
        if s is None:
            new.append({"row": r["_row"], "job": r.get("job"), "mbl": r["mbl"], "hbl": r.get("hbl"),
                        "consignee": r.get("consignee")})
            continue
        seen.add(s.id)
        if s.is_deleted:
            deleted.append(f"{r.get('_where', 'Row')}: {s.mbl or s.job} was deleted in the app — restore it to update it")
            continue
        has_be = _has_doc(s, DocumentType.ASSESSED_BILL_OF_ENTRY, DocumentType.OOC_BILL_OF_ENTRY)
        has_ooc = _has_doc(s, DocumentType.OOC_BILL_OF_ENTRY)
        changes, kept = [], []
        for field, value in r.items():
            if field.startswith("_"):
                continue
            old = getattr(s, field, None)
            if _norm_value(old) == _norm_value(value) or (old in (None, "") and value in (None, "", False) and field != "is_billed"):
                continue
            if field in IGM_DETAILS and value in (None, ""):
                continue
            entry = {"field": field, "label": LABELS.get(field, field.replace("_", " ").title()),
                     "old": _show(old), "new": _show(value)}
            if has_be and field in FROM_BE and old not in (None, ""):
                kept.append({**entry, "why": "kept from BE"})
            elif has_ooc and field in FROM_OOC and old and not value:
                kept.append({**entry, "why": "kept from OOC copy"})
            else:
                changes.append(entry)
        if changes or kept:
            updated.append({"shipment_id": s.id, "row": r["_row"], "job": s.job, "mbl": s.mbl,
                            "matched_by": how, "check": how in ("BE No", "Job"), "changes": changes, "kept": kept})
        else:
            unchanged += 1
    gone = [s for s in ships if s.id not in seen and not s.is_deleted]
    missing = [{"shipment_id": s.id, "job": s.job, "mbl": s.mbl, "consignee": s.consignee}
               for s in gone if not (s.is_billed or s.cleared_date)]
    return {"rows": len(rows), "new": new, "updated": updated, "unchanged": unchanged, "missing": missing,
            "cleared": len(gone) - len(missing), "older": older, "deleted": deleted}


def apply(db: Session, rows: list[dict], user_id: Optional[int]) -> dict:
    """Write the import (same plan as the preview, re-made under the locks). Caller commits."""
    p = plan(db, rows, lock=True)
    by_row = {r["_row"]: r for r in rows}
    hs = db.query(HSCode).filter(HSCode.code == TYRE_HS_CODE).first()
    now = datetime.now()

    for item in p["updated"]:
        s = db.get(Shipment, item["shipment_id"])
        r = by_row[item["row"]]
        fields = {c["field"] for c in item["changes"]}
        for f in fields - {"is_billed"}:
            record_change(db, "shipments", s.id, f, getattr(s, f), r[f], user_id)
            setattr(s, f, r[f])
        if "consignee" in fields:
            s.apply_hss_from_consignee()
        if "is_billed" in fields:
            _set_billed(db, s, bool(r["is_billed"]), now, user_id)
        elif fields & EVIDENCE_FIELDS:
            st = status_after_evidence_change(s)
            if st is not None and st != s.status:
                record_change(db, "shipments", s.id, "status", s.status, st, user_id)
                s.status = st
        if s.missing_from_sheet_at is not None:
            s.missing_from_sheet_at = None

    for item in p["new"]:
        r = {k: v for k, v in by_row[item["row"]].items() if not k.startswith("_")}
        billed = r.pop("is_billed", False)
        s = Shipment(**r, hs_code_id=hs.id if hs else None)
        s.apply_hss_from_consignee()
        s.status = proven_status(s)
        db.add(s)
        db.flush()
        record_change(db, "shipments", s.id, "created", None, "tracker CSV import", user_id)
        if billed:
            _set_billed(db, s, True, now, user_id)

    for m in p["missing"]:
        s = db.get(Shipment, m["shipment_id"])
        if s.missing_from_sheet_at is None:
            s.missing_from_sheet_at = now
            record_change(db, "shipments", s.id, "missing_from_sheet", None, now.isoformat(), user_id)
    # back in the sheet -> clear an old flag
    still_missing = {m["shipment_id"] for m in p["missing"]}
    for s in db.query(Shipment).filter(Shipment.missing_from_sheet_at.isnot(None)):
        if s.id not in still_missing:
            s.missing_from_sheet_at = None
    return p


def _set_billed(db: Session, s: Shipment, billed: bool, now: datetime, user_id: Optional[int]) -> None:
    if billed and not s.is_billed:
        for f, v in (("is_billed", True), ("is_archived", True), ("billed_at", now), ("status", ShipmentStatus.BILLED)):
            record_change(db, "shipments", s.id, f, getattr(s, f), v, user_id)
            setattr(s, f, v)
    elif not billed and s.is_billed:
        restored = proven_status(s)
        for f, v in (("is_billed", False), ("is_archived", False), ("billed_at", None), ("status", restored)):
            record_change(db, "shipments", s.id, f, getattr(s, f), v, user_id)
            setattr(s, f, v)

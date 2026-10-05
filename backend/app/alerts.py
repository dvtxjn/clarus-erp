"""
Dashboard alerts — "Needs attention" (client, 2026-09-30).

Three kinds, all for live shipments (no Cleared Date yet):
- deadline:  ETA marked "d" — the shipment must be moved to the CFS 4 days before the ETA.
- free_days: 14 free days at the POD, counted from the inward date inclusive (INW = day 1).
             Sea ports only: for inland ports (Panipat, Garhi, …) the INW is the sea-port inward and
             the free days start on arrival at the FPOD after the rail leg — counted later from the
             client's FPOD inward sheet (P5).
- documents: BE not filed yet, the ship is close (ETA within 7 days, or already inward) and
             basic documents on the checklist aren't attached in the ERP yet. Wording is "not attached",
             never "missing": the papers have arrived, they just aren't uploaded (client, 2026-09-30).

Pure functions (no DB) so they're easy to test; the router feeds them.
"""
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from app.core.enums import DocumentType

DEADLINE_DAYS = 4        # move to CFS this many days before the ETA
FREE_DAYS = 14           # free days at the POD, INW inclusive
WARN_DAYS = 3            # start warning this many days ahead
DOCS_BEFORE_ETA = 7      # chase missing documents from this many days before the ETA
IGM_BEFORE_ETA = 2       # the IGM should be on ICEGATE by then; if not, the BL no. may be fed wrong

# sea ports (client, 2026-09-30): the INW here is where the free days start.
# Every other port (Panipat, Garhi, …) is inland and skipped until the FPOD inward sheet exists.
SEA_PORTS = {"INMUN1", "INNSA1"}

# free days at an inland ICD from each container's arrival (ground rent); anything not listed: FREE_DAYS
ICD_FREE_DAYS: dict[str, int] = {}  # every ICD: standard 14 (client, 2026-10-05: no 21-day exception)


def icd_free_days(port: Optional[str]) -> int:
    return ICD_FREE_DAYS.get((port or "").upper(), FREE_DAYS)

# the documents needed to file the BE (the "Basic" group in the Document Manager)
BASIC_DOCUMENTS = {
    DocumentType.BL_COPY, DocumentType.HBL_COPY, DocumentType.COMMERCIAL_INVOICE, DocumentType.PACKING_LIST,
    DocumentType.CERTIFICATE_OF_ORIGIN, DocumentType.FTA_CERTIFICATE_OF_ORIGIN, DocumentType.FORM_6_9,
    DocumentType.FORM_6, DocumentType.FORM_9, DocumentType.INSURANCE, DocumentType.HSS_AGREEMENT,
}

# the office's short codes (client, 2026-09-30)
DOC_LABELS = {
    DocumentType.BL_COPY: "BL", DocumentType.HBL_COPY: "HBL",
    DocumentType.COMMERCIAL_INVOICE: "ComInv", DocumentType.PACKING_LIST: "PL",
    DocumentType.CERTIFICATE_OF_ORIGIN: "COO", DocumentType.FTA_CERTIFICATE_OF_ORIGIN: "FTA COO",
    DocumentType.FORM_6_9: "F6,9", DocumentType.FORM_6: "F6", DocumentType.FORM_9: "F9",
    DocumentType.INSURANCE: "Insurance", DocumentType.HSS_AGREEMENT: "HSS",
}

_INW_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")


def parse_inw(value: Optional[str]) -> Optional[date]:
    """The inward date is free text in the tracker ('Pending', '19-Sep-2026', …)."""
    for fmt in _INW_FORMATS:
        try:
            return datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def _severity(days_left: int) -> str:
    """overdue < urgent (today / tomorrow) < soon."""
    if days_left < 0:
        return "overdue"
    if days_left <= 1:
        return "urgent"
    return "soon"


def _days(n: int) -> str:
    return f"{n} day" if abs(n) == 1 else f"{n} days"


def _base(s) -> dict:
    # every alert row shows both BE and BL (client rule)
    return {"shipment_id": s.id, "job": s.job, "mbl": s.mbl, "be_no": s.be_no,
            "client": s.client, "consignee": s.consignee, "port": s.port}


def deadline_alert(s, today: date) -> Optional[dict]:
    if not s.eta_is_deadline or not s.eta:
        return None
    due = s.eta - timedelta(days=DEADLINE_DAYS)
    left = (due - today).days
    if left > WARN_DAYS:
        return None
    if left < 0:
        text = f"Move to CFS was due {due:%d %b} ({_days(-left)} ago)"
    elif left == 0:
        text = "Move to CFS today"
    else:
        text = f"Move to CFS by {due:%d %b} ({_days(left)} left)"
    return {**_base(s), "kind": "deadline", "severity": _severity(left), "days_left": left,
            "due": due.isoformat(), "text": text}


def last_free_day(start: date) -> date:
    """Free days are counted inclusively: the start day is day 1."""
    return start + timedelta(days=FREE_DAYS - 1)


def free_days_alert(s, today: date) -> Optional[dict]:
    if (s.port or "").upper() not in SEA_PORTS:
        return None                                # inland: free days start at the FPOD (later)
    inw = parse_inw(s.inw)
    if inw is None or inw > today:
        return None
    day = (today - inw).days + 1                  # INW itself is day 1
    last_free = inw + timedelta(days=FREE_DAYS - 1)
    left = (last_free - today).days               # 0 = today is the last free day
    if left > WARN_DAYS:
        return None
    if left < 0:
        text = f"Day {day}: free days ended {last_free:%d %b} ({_days(-left)} over)"
    elif left == 0:
        text = f"Day {day}: last free day today"
    else:
        text = f"Day {day}: free days end {last_free:%d %b} ({_days(left)} left)"
    return {**_base(s), "kind": "free_days", "severity": _severity(left), "days_left": left,
            "due": last_free.isoformat(), "text": text}


def fpod_alert(s, containers: Iterable[tuple], today: date) -> Optional[dict]:
    """Inland: free days run per container from its arrival at the ICD (standard 14, typed per container
    otherwise). containers = (container_no, arrival_date, free_days or None). One line for the shipment;
    the per-container detail is on the Overview."""
    if (s.port or "").upper() in SEA_PORTS:
        return None
    standard = icd_free_days(s.port)
    arrived = [(no, arr + timedelta(days=(fd if fd is not None else standard) - 1)) for no, arr, fd in containers if arr]
    if not arrived:
        return None
    close = sorted(((last - today).days, last, no) for no, last in arrived if (last - today).days <= WARN_DAYS)
    if not close:
        return None
    left, last, _ = close[0]
    n, total = len(close), len(arrived)
    who = f"{n} of {total} container{'s' if total != 1 else ''}"
    if left < 0:
        text = f"{who} at the ICD past free days (ended {last:%d %b}, {_days(-left)} over)"
    elif left == 0:
        text = f"{who} at the ICD: last free day today"
    else:
        text = f"{who} at the ICD: free days end {last:%d %b} ({_days(left)} left)"
    return {**_base(s), "kind": "free_days", "severity": _severity(left), "days_left": left,
            "due": last.isoformat(), "text": text}


def documents_alert(s, required: Iterable[tuple], uploaded: set, today: date) -> Optional[dict]:
    """required = (document_type, optional) pairs from the shipment's HS code checklist;
    uploaded = document types on file (a combined file already expanded to its parts)."""
    if s.be_no:
        return None                                # BE filed: this check is over
    inw = parse_inw(s.inw)
    if s.eta is None and inw is None:
        return None
    left = (s.eta - today).days if s.eta else 0
    if inw is None and left > DOCS_BEFORE_ETA:
        return None
    missing = [t for t, optional in required if t in BASIC_DOCUMENTS and not optional and t not in uploaded]
    if not missing:
        return None
    names = ", ".join(DOC_LABELS.get(t, t.value) for t in missing)
    when = "arrived" if inw or left < 0 else ("ETA today" if left == 0 else f"ETA in {_days(left)}")
    return {**_base(s), "kind": "documents", "severity": "urgent" if inw or left <= 2 else "soon",
            "days_left": left, "due": s.eta.isoformat() if s.eta else None,
            "text": f"Not attached yet: {names} (BE not filed, {when})", "missing": [t.value for t in missing]}


def lookup_alert(s, today: date) -> Optional[dict]:
    """ICEGATE lookup (client, 2026-09-30: a miss costs money daily): within 2 days of the ETA (or past it) and
    ICEGATE still hasn't given us the IGM — no BL entered, the lookup failing, or nothing found (the BL no. may
    be fed wrong). Cleared by itself once a lookup finds it."""
    if s.eta is None or s.be_no:
        return None
    left = (s.eta - today).days
    if left > IGM_BEFORE_ETA:
        return None
    rec = s.icegate or {}
    when = f"ETA passed {_days(-left)} ago" if left < 0 else ("ETA today" if left == 0 else f"ETA in {_days(left)}")
    if not (s.mbl or "").strip():
        text = f"No BL no. entered — ICEGATE can't be checked ({when})"
    elif rec.get("error") and rec.get("error_at", "") >= rec.get("fetched_at", ""):
        text = f"ICEGATE lookup failing: {rec['error']} ({when}) — try again"
    elif s.igm or s.inw or rec.get("sea_found") or rec.get("icd_found"):
        return None
    else:
        from app import liners  # late: keeps this module import-light

        known = liners.identify(s.mbl)
        hint = known["note"] if known and known["note"] else (
            "BL format not recognised" if not known else "IGM may not be filed yet")
        looked = f", last looked {rec['fetched_at'].replace('T', ' ')}" if rec.get("fetched_at") else ", not looked up yet"
        text = f"IGM not found on ICEGATE ({when}{looked}) — check the BL no. ({hint})"
    return {**_base(s), "kind": "icegate", "severity": _severity(left), "days_left": left,
            "due": s.eta.isoformat(), "text": text, "lookup": True}


_ORDER = {"overdue": 0, "urgent": 1, "soon": 2}


def sort_alerts(alerts: list[dict]) -> list[dict]:
    return sorted(alerts, key=lambda a: (_ORDER[a["severity"]], a["days_left"], a["job"] or ""))

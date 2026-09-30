"""
Dashboard alerts — "Needs attention" (client, 2026-09-30).

Three kinds, all for live shipments (no Cleared Date yet):
- deadline:  ETA marked "d" — the shipment must be moved to the CFS 4 days before the ETA.
- free_days: 14 free days at the POD, counted from the inward date inclusive (INW = day 1).
             Sea ports only: for inland ports (Panipat, Garhi, …) the INW is the sea-port inward and
             the free days start on arrival at the FPOD after the rail leg — counted later from the
             client's FPOD inward sheet (P5).
- documents: BE not filed yet, the ship is close (ETA within 7 days, or already inward) and
             basic documents on the shipment's checklist are still missing.

Pure functions (no DB) so they're easy to test; the router feeds them.
"""
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from app.core.enums import DocumentType

DEADLINE_DAYS = 4        # move to CFS this many days before the ETA
FREE_DAYS = 14           # free days at the POD, INW inclusive
WARN_DAYS = 3            # start warning this many days ahead
DOCS_BEFORE_ETA = 7      # chase missing documents from this many days before the ETA

# sea ports (client, 2026-09-30): the INW here is where the free days start.
# Every other port (Panipat, Garhi, …) is inland and skipped until the FPOD inward sheet exists.
SEA_PORTS = {"INMUN1", "INNSA1"}

# the documents needed to file the BE (the "Basic" group in the Document Manager)
BASIC_DOCUMENTS = {
    DocumentType.BL_COPY, DocumentType.HBL_COPY, DocumentType.COMMERCIAL_INVOICE, DocumentType.PACKING_LIST,
    DocumentType.CERTIFICATE_OF_ORIGIN, DocumentType.FTA_CERTIFICATE_OF_ORIGIN, DocumentType.FORM_6_9,
    DocumentType.FORM_6, DocumentType.FORM_9, DocumentType.INSURANCE, DocumentType.HSS_AGREEMENT,
}

DOC_LABELS = {
    DocumentType.BL_COPY: "BL copy", DocumentType.HBL_COPY: "HBL copy",
    DocumentType.COMMERCIAL_INVOICE: "Commercial invoice", DocumentType.PACKING_LIST: "Packing list",
    DocumentType.CERTIFICATE_OF_ORIGIN: "Certificate of origin", DocumentType.FTA_CERTIFICATE_OF_ORIGIN: "FTA COO",
    DocumentType.FORM_6_9: "Form 6 & 9", DocumentType.FORM_6: "Form 6", DocumentType.FORM_9: "Form 9",
    DocumentType.INSURANCE: "Insurance", DocumentType.HSS_AGREEMENT: "HSS agreement",
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
            "text": f"BE not filed, {when}: missing {names}", "missing": [t.value for t in missing]}


_ORDER = {"overdue": 0, "urgent": 1, "soon": 2}


def sort_alerts(alerts: list[dict]) -> list[dict]:
    return sorted(alerts, key=lambda a: (_ORDER[a["severity"]], a["days_left"], a["job"] or ""))

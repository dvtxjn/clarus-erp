"""
Read one ICEGATE e-mail (.eml bytes) into an event (client, 2026-09-30, P1). Only mails from
@icegate.gov.in are read; anything else comes back as None and is never stored.

Kinds use LiveImpex's ICEGATE communicator names, so the office sees the words it knows. Built from
real mails (samples/icegate-mails, kept out of git):

  subject                                          kind              carries
  Job number 175_CACHI01_Success  + .ack           be_ack            job -> BE no/date, port
  BE number 3918277_CACHI01_Success + .ack (A)     be_ack_amend      amendment accepted
  Job number 183_CACHI01_Failed   + .nak           be_nak            job, port, error code   (attention)
  Bill Of Entry ("... has been rejected. Error")   be_rejected       job, error code
  On Submission                                    be_submitted      job, date
  Bill of entry number generated                   be_generated      BE no
  Electronic first copy of BoE ... + PDF           processed_be      assessed BE copy
  Bill of Entry Examination Instructions           exam_order        prescribed or not
  Bill of entry pending for query reply            be_query          BE no                   (attention)
  Outbound file generated + .out                   be_query          BE no, query text       (attention)
  Supplementary filing processed                   supplementary     BE no
  Electronic Final OOC copy ... + PDF              out_of_charge     OOC copy
  Electronic eGatepass copy ... + PDF              gate_pass         gatepass copy
  Document upload confirmation + .dms              esanchit          documents uploaded, MBL
  Filing status - ... Header validation failed     filing_failed     control no              (attention)
"""
from __future__ import annotations

import email
import html
import re
from datetime import date, datetime, timedelta, timezone
from email import policy
from email.utils import parsedate_to_datetime
from typing import Optional

LABELS = {
    "be_submitted": "Submit B/E",
    "be_ack": "B/E Acknowledgement",
    "be_ack_amend": "B/E Acknowledgement (Amendment)",
    "be_nak": "B/E Negative Acknowledgement",
    "be_rejected": "B/E Rejected",
    "be_generated": "BE number generated",
    "processed_be": "Processed B/E",
    "exam_order": "B/E Examination Order",
    "be_query": "B/E Query",
    "supplementary": "Supplementary filing",
    "out_of_charge": "Out of Charge",
    "gate_pass": "OOC Gate Pass",
    "esanchit": "eSANCHIT upload",
    "filing_failed": "Filing failed",
    "otp": "ICEGATE login OTP",
}
ATTENTION = {"be_nak", "be_query", "filing_failed"}
PDF_DOC = {"processed_be": "ASSESSED_BILL_OF_ENTRY", "out_of_charge": "OOC_BILL_OF_ENTRY",
           "gate_pass": "GATEPASS_BILL_OF_ENTRY"}
SEP = "\x1d"  # ICEGATE flat files: group-separator between fields


def _date8(s: Optional[str]) -> Optional[date]:
    """'29092026' (ddmmyyyy) or '20260929' (yyyymmdd) -> date."""
    s = (s or "").strip()
    for fmt in ("%d%m%Y", "%Y%m%d", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            if 2000 < d.year < 2100:
                return d
        except ValueError:
            pass
    return None


def _received(msg) -> Optional[datetime]:
    raw = msg.get("Date", "")
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        ist = timezone(timedelta(hours=5, minutes=30))
        return datetime.strptime(raw.strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=ist)  # "29-SEP-2026 13:34:49", IST
    except ValueError:
        return None


def _text(msg) -> str:
    for part in msg.walk():
        if part.get_content_maintype() == "text" and not part.get_filename():
            raw = part.get_payload(decode=True) or b""
            t = raw.decode(part.get_content_charset() or "utf-8", "replace")
            if part.get_content_type() == "text/html":
                t = re.sub(r"(?is)<(style|script).*?</\1>", "", t)
                t = html.unescape(re.sub(r"<[^>]+>", " ", t))
            t = re.sub(r"[ \t\xa0]+", " ", t)
            return re.sub(r"\n\s*\n+", "\n", t).strip()
    return ""


def _attachments(msg) -> list[tuple[str, bytes]]:
    return [(p.get_filename(), p.get_payload(decode=True) or b"") for p in msg.walk() if p.get_filename()]


def _flat_records(data: bytes, tag: str) -> list[list[str]]:
    """Rows of an ICEGATE flat file (.ack / .nak / .out / .dms) starting with tag (F / A)."""
    out = []
    for line in data.decode("latin-1").split("\n"):  # not splitlines(): it splits on \x1d too
        line = line.rstrip("\r")
        if line.startswith("<START-"):
            break
        f = line.split(SEP) if SEP in line else line.split("|")
        if f and f[0] == tag:
            out.append(f)
    return out


def parse(raw: bytes) -> Optional[dict]:
    msg = email.message_from_bytes(raw, policy=policy.compat32)
    sender = (msg.get("From") or "").lower()
    if "icegate.gov.in" not in sender:
        return None
    subject = re.sub(r"\s+", " ", str(email.header.make_header(email.header.decode_header(msg.get("Subject") or "")))).strip()
    body, atts = _text(msg), _attachments(msg)
    ev: dict = {"message_id": (msg.get("Message-ID") or "").strip() or None, "received_at": _received(msg),
                "subject": subject, "kind": None, "be_no": None, "be_date": None, "job_no": None, "port": None,
                "mbl": None, "summary": None, "detail": {}, "pdf": None}
    s = subject.lower()

    def from_ack(name_ext: str, tag: str = "F") -> Optional[list[str]]:
        for name, data in atts:
            if name.lower().endswith(name_ext):
                recs = _flat_records(data, tag)
                if recs:
                    return recs[0]
        return None

    if s.startswith("otp"):
        # ICEGATE login OTP (client: important). The code is shown to the admin only, while it's valid (10 min)
        m = re.search(r"\b(\d{4,8})\b is the OTP", body)
        ev.update(kind="otp", summary="ICEGATE login OTP")
        ev["detail"].update(otp=m.group(1) if m else None, icegate_id=(re.search(r"ICEGATE ID\s*(\S+)", subject) or [None, None])[1])
    elif m := re.match(r"job number (\d+)_\w+_(success|failed)", s):
        ev["job_no"] = m.group(1)
        if m.group(2) == "success":
            ev["kind"] = "be_ack"
            f = from_ack(".ack")
            if f and len(f) > 5:  # F|port|job|job date|BE no|BE date|...
                ev.update(port=f[1] or None, be_no=f[4] or None, be_date=_date8(f[5]))
                ev["detail"]["job_date"] = str(_date8(f[3]) or "")
            ev["summary"] = f"Accepted: BE {ev['be_no']}" if ev["be_no"] else "Filing accepted"
        else:
            ev["kind"] = "be_nak"
            f = from_ack(".nak")
            code = None
            if f:
                ev["port"] = f[1] or None
                rest = [x for x in f[4:] if x]
                code = " ".join(rest) or None
            ev["detail"]["error"] = code
            ev["summary"] = f"Rejected by ICEGATE — error {code}" if code else "Rejected by ICEGATE"
    elif m := re.match(r"be number (\d+)_\w+_success", s):
        ev.update(kind="be_ack_amend", be_no=m.group(1))
        f = from_ack(".ack", "A")
        if f and len(f) > 2:
            ev["port"] = f[1] or None
        ev["summary"] = "Amendment accepted"
    elif s == "bill of entry" and "rejected" in body.lower():
        m = re.search(r"job no\.?\s*(\d+)\s*dated\s*(\d{8}).*?error code:\s*([^\n\"]+)", body, re.I | re.S)
        ev["kind"] = "be_rejected"
        if m:
            ev["job_no"], ev["detail"]["error"] = m.group(1), m.group(3).strip()
        ev["summary"] = f"Rejected — error {ev['detail'].get('error') or '?'}"
    elif s == "on submission":
        m = re.search(r"job no\.?\s*(\d+)\s*dated\s*(\d{8})", body, re.I)
        ev["kind"] = "be_submitted"
        if m:
            ev["job_no"] = m.group(1)
        ev["summary"] = "Bill of entry submitted"
    elif s.startswith("bill of entry number generated"):
        m = re.search(r"BE number\s*(\d+)", body, re.I)
        ev.update(kind="be_generated", be_no=m.group(1) if m else None)
        ev["summary"] = f"BE number {ev['be_no']} generated"
    elif m := re.match(r"electronic (first|final ooc|egatepass) copy of boe .*no\s*(\d+)\s*dt\s*(\d{8})", s):
        ev["kind"] = {"first": "processed_be", "final ooc": "out_of_charge", "egatepass": "gate_pass"}[m.group(1)]
        ev.update(be_no=m.group(2), be_date=_date8(m.group(3)))
        pdf = next(((n, d) for n, d in atts if n.lower().endswith(".pdf")), None)
        if pdf:
            ev["pdf"] = {"name": pdf[0], "data": pdf[1], "doc_type": PDF_DOC[ev["kind"]]}
            pm = re.match(r"\d{7}\d{8}([A-Z]{3}[A-Z0-9]{3})BE", pdf[0])  # BE no + date + port + "BE"
            ev["port"] = pm.group(1) if pm else None
        ev["summary"] = {"processed_be": "Assessed BE copy received", "out_of_charge": "Out of charge — OOC copy received",
                         "gate_pass": "OOC gate pass (e-Gatepass) received"}[ev["kind"]]
    elif s.startswith("bill of entry examination instructions"):
        m = re.search(r"Bill of Entry No\s*(\d+)\s*dated\s*(\d{2}/\d{2}/\d{4})\s*filed at\s*([A-Z0-9]{6})", body, re.I)
        ev["kind"] = "exam_order"
        if m:
            ev.update(be_no=m.group(1), be_date=_date8(m.group(2)), port=m.group(3).upper())
        order = re.search(r"Examination Order\s*:\s*(.+?)\s*(?:CCR Examination|Warm Regards|$)", body, re.I | re.S)
        order_text = re.sub(r"\s+", " ", order.group(1)).strip() if order else ""
        prescribed = bool(order_text) and "not been prescribed" not in order_text.lower()
        ev["detail"].update(order=order_text or None, prescribed=prescribed)
        ev["summary"] = f"Examination ordered: {order_text}" if prescribed else "No examination prescribed"
    elif s.startswith("bill of entry pending for query reply"):
        m = re.search(r"BE number\s*(\d+)\s*dated\s*(\d{4}-\d{2}-\d{2})", body, re.I)
        ev["kind"] = "be_query"
        if m:
            ev.update(be_no=m.group(1), be_date=_date8(m.group(2)))
        ev["summary"] = "Query raised — reply needed"
    elif s.startswith("outbound file generated"):
        f = from_ack(".out")
        if f and len(f) >= 7:  # F|port|BE no|BE date|n|query date|query text
            ev.update(kind="be_query", port=f[1] or None, be_no=f[2] or None, be_date=_date8(f[3]))
            q = re.sub(r"\s+", " ", f[6]).strip()
            ev["detail"]["query"] = q
            ev["summary"] = f"Query: {q}"
    elif s.startswith("supplementary filing processed"):
        m = re.search(r"BE no\.?\s*(\d+)", body, re.I)
        ev.update(kind="supplementary", be_no=m.group(1) if m else None, summary="Supplementary filing processed")
    elif s.startswith("document upload confirmation"):
        ev["kind"] = "esanchit"
        docs = []
        for name, data in atts:
            if name.lower().endswith((".dms", ".dms_")):
                for f in _flat_records(data, "F"):
                    if len(f) > 6:
                        docs.append({"file": f[1], "irn": f[2], "code": f[5], "type": f[6].strip()})
        ev["detail"]["documents"] = docs
        refs = {m.group(1) for d in docs if (m := re.search(r"IMPDOC_\d+_([A-Z0-9]+)-", d["file"]))}
        ev["mbl"] = next(iter(refs)) if len(refs) == 1 else None
        ev["summary"] = f"{len(docs)} document(s) uploaded: " + ", ".join(d["type"] for d in docs)
    elif s.startswith("filing status"):
        m = re.search(r"control no\.?\s*(\d+).*?Receiver ID\s*([A-Z0-9]{6})", body, re.I | re.S)
        ev["kind"] = "filing_failed" if "failed" in body.lower() else "other"
        if m:
            ev["port"] = m.group(2)
            ev["detail"]["control_no"] = m.group(1)
        first = next((ln for ln in body.splitlines() if "failed" in ln.lower()), body[:200])
        ev["summary"] = first.strip()
    else:  # every other ICEGATE mail (export S/B, CIM, SCMTR, …) is kept too, labelled by its subject
        ev["kind"] = "other"
    ev["summary"] = ev["summary"] or subject
    ev["detail"]["attachments"] = [n for n, _ in atts]
    ev["label"] = LABELS.get(ev["kind"], subject)
    ev["attention"] = ev["kind"] in ATTENTION
    return ev

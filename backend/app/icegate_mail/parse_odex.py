"""
ODeX mails (notification@odexservices.com) — the shipping lines' DO / invoice portal (client, 2026-09-30).
Built from real mails (the office's ODeX notifications, Sep 2026):

  subject                                                        kind                    carries
  ODeX: DO Released for <BL>                                     odex_do_released        DO no + date
  ODeX: Invoices Requested for <BL>,<Location>                   odex_invoice_requested  delivery type, consignee
  ODeX: Invoices Re-Requested for <BL>,<Location>                odex_invoice_requested  + containers, valid till
  ODeX: Invoices Received for <BL>                               odex_invoice_received   invoice no / type / amount / party
  ODeX: Notification Mail for Rejecting of DO Request for BL No. odex_do_rejected        the line's remarks  (attention)
  ODeX: KYC OR Registration Pending                              odex_kyc_pending        consignee           (attention)
  ODeX: Your Request for CFS for MBL No. <BL> is Confirmed/…     odex_cfs                CFS code + name, status
  IGM Filed for BL No.<BL> by <line>                             odex_igm_filed          line
Anything else from ODeX is kept as odex_other. Replies by people ("Re: ODeX: …") are not ODeX's own mail
and are not read. No port is set: ODeX's "Location" is the gateway, and an inland shipment's port is the
ICD — the BL alone finds the shipment.
"""
from __future__ import annotations

import email
import html
import re
from email import policy
from typing import Optional

LABELS = {
    "odex_do_released": "ODeX: DO released",
    "odex_invoice_requested": "ODeX: invoices requested",
    "odex_invoice_received": "ODeX: line invoices received",
    "odex_do_rejected": "ODeX: DO request rejected",
    "odex_kyc_pending": "ODeX: KYC pending",
    "odex_cfs": "ODeX: CFS request",
    "odex_igm_filed": "ODeX: IGM filed",
    "odex_other": "ODeX: other",
}
ATTENTION = {"odex_do_rejected", "odex_kyc_pending"}
BL = r"([A-Z0-9]{6,25})"


def is_odex(sender: str) -> bool:
    return "odexservices.com" in (sender or "").lower()


def _text(msg) -> str:
    """The body with its line breaks (ODeX mails are HTML tables: the HTML part first, else the plain one)."""
    parts = [p for p in msg.walk() if p.get_content_maintype() == "text" and not p.get_filename()]
    parts.sort(key=lambda p: p.get_content_type() != "text/html")
    if not parts:
        return ""
    part = parts[0]
    t = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
    if part.get_content_type() == "text/html":
        t = re.sub(r"(?is)<(style|script).*?</\1>", "", t)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>|</h\d>", "\n", t)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _field(body: str, name: str) -> Optional[str]:
    m = re.search(rf"^[ \t]*{name}[ \t]*:?[ \t]*(.*)$", body, re.I | re.M)  # never runs into the next line
    v = (m.group(1).strip() if m else "") or None
    return v


def parse(raw: bytes, ev: dict, subject: str) -> dict:
    """Fill the event (already carrying message_id / received_at / subject) for an ODeX mail."""
    msg = email.message_from_bytes(raw, policy=policy.compat32)
    body = _text(msg)
    s = subject
    d = ev["detail"]
    kind = "odex_other"
    if m := re.search(rf"DO Released for {BL}", s, re.I):
        kind, ev["mbl"] = "odex_do_released", m.group(1)
        dm = re.search(r"DO Number\s+DO date\s*\n?\s*(\S+)\s+(\d{2}-\d{2}-\d{4})", body, re.I)
        if dm:
            d.update(do_no=dm.group(1), do_date=dm.group(2))
        line = re.search(r"on behalf of (.+?)\s*$", body, re.I | re.M)
        d["line"] = line.group(1).strip() if line else None
        ev["summary"] = f"DO {d.get('do_no') or '—'} dated {d.get('do_date') or '—'}" + (f" · {d['line']}" if d.get("line") else "")
    elif m := re.search(rf"Invoices (Re-)?Requested for {BL},\s*(.+)$", s, re.I):
        kind, ev["mbl"] = "odex_invoice_requested", m.group(2)
        d.update(again=bool(m.group(1)), location=m.group(3).strip(), delivery=_field(body, "Type Of Delivery"),
                 consignee=_field(body, r"Consignee/Buyer Name"), valid_till=_field(body, "Valid Till"),
                 free_days=_field(body, "Free Days"), do_extension=_field(body, "DO Extension"),
                 line=(_field(body, "Liner") or "").split(" - for ")[0] or None)
        d["containers"] = re.findall(r"^\s*([A-Z]{4}\d{7})\s+(\S+)\s+(\d{2}-\d{2}-\d{4})", body, re.M)
        ev["summary"] = ("Invoices re-requested" if d["again"] else "Invoices requested") + \
            f" · {d.get('delivery') or ''} · {d['location']}" + (f" · valid till {d['valid_till']}" if d.get("valid_till") else "")
    elif m := re.search(rf"Invoices Received for {BL}", s, re.I):
        kind, ev["mbl"] = "odex_invoice_received", m.group(1)
        inv = re.findall(r"^[ \t]*([A-Z0-9/-]{6,})[ \t]+(NON FREIGHT|FREIGHT|[A-Z ]{3,20}?)[ \t]+([\d,]+(?:\.\d{1,2})?)[ \t]+(.+?)[ \t]*$",
                         body, re.M)
        d["invoices"] = [{"no": a, "type": b.strip(), "amount": c.replace(",", ""), "party": p} for a, b, c, p in inv]
        d["delivery"] = _field(body, "Type Of Delivery")
        total = sum(float(x["amount"]) for x in d["invoices"])
        ev["summary"] = (f"{len(d['invoices'])} invoice(s), ₹{total:,.2f}: " + ", ".join(f"{x['no']} ({x['type']})" for x in d["invoices"])
                         if d["invoices"] else "Line invoices released")
    elif m := re.search(rf"Rejecting of DO Request for BL No\.?\s*{BL}", s, re.I):
        kind, ev["mbl"] = "odex_do_rejected", m.group(1)
        rm = re.search(rf"{ev['mbl']}\*?\s*(.+?)(?:\n\s*Note:|\Z)", body.split("Remarks", 1)[-1], re.S)
        d["remarks"] = re.sub(r"\s+", " ", rm.group(1)).strip()[:600] if rm else None
        lm = re.search(r"Notification Mail for Rejecting of DO Request for BL No\.?\s*\S+\s+by\s+(.+)$", s, re.I)
        d["line"] = lm.group(1).strip() if lm else None
        ev["summary"] = "DO request rejected" + (f": {d['remarks']}" if d.get("remarks") else "")
    elif re.search(r"KYC OR Registration Pending", s, re.I):
        kind = "odex_kyc_pending"
        d["consignee"] = _field(body, "Consignee")
        ev["summary"] = f"KYC / ODeX registration pending for {d['consignee'] or 'the consignee'} — send PAN, GST no, GST address proof"
    elif m := re.search(rf"Request for CFS for MBL No\.?\s*{BL}\s+is\s+(\w+)", s, re.I):
        kind, ev["mbl"] = "odex_cfs", m.group(1)
        d["status"] = m.group(2).title()
        cm = re.search(rf"{m.group(1)}\s+(\S+)\s+-\s+(.+?)\s+{m.group(2)}", body, re.I)
        if cm:
            d.update(cfs_code=cm.group(1), cfs_name=cm.group(2).strip())
        ev["summary"] = f"CFS request {d['status']}" + (f": {d.get('cfs_name')}" if d.get("cfs_name") else "")
    elif m := re.search(rf"IGM Filed for BL No\.?\s*{BL}(?:\s+by\s+(.+))?", s, re.I):
        kind, ev["mbl"] = "odex_igm_filed", m.group(1)
        d["line"] = (m.group(2) or "").strip() or None
        ev["summary"] = "IGM filed — line invoices to follow" + (f" ({d['line']})" if d.get("line") else "")
    ev["kind"] = kind
    ev["summary"] = ev.get("summary") or subject
    ev["label"] = LABELS[kind] if kind != "odex_other" else f"ODeX: {subject[:60]}"
    ev["attention"] = kind in ATTENTION
    ev["source"] = "odex"
    return ev

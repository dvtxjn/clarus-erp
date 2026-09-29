"""
Shipping line destination charges invoices (imports) -> totals + charge lines.

Every shipping line prints its own layout, so this is label-based with a list
of patterns per figure; add a pattern when a new line's invoice doesn't read.
Samples it's built from (reference: client uploads, 2026-09-28):

  Maersk (tax invoice, 2 per BL is normal — e.g. THC/haulage/doc fee + a
  separate "Additional Import Service"):
      Terminal Handling Service - Destination 10 CNT 15,750.00 INR 157,500.00 IN IGST 18% 28,350.00 157,500.00
      SAC/HSN 996711
      Total Base Amount INR 1,102,760.00
      I-GST Total taxes (see tax specification) INR 198,496.80
      Total Payable Amount INR 1,301,256.80
      Bill of Lading 274014260
  Cordelia (proforma):
      5 INR 23,180 115,900 1.0 115,900
      THC- TERMINAL HANDLING CHARGES - NSFT (SAC:996711)
      Taxable Amount 135,500 / SGST (%) 9% INR 12,195 / CGST (%) 9% INR 12,195 / Total Amount INR 159,890
      HBL # : CSX26JEDNSA021814

Returns the same amount keys as the CFS reader (cfs_before_tax / cfs_gst /
cfs_after_tax / cfs_sanity_ok) so tracker sync treats all invoices alike, plus
carrier, invoice_no, is_proforma and `charges` (one dict per charge line).
Client rule (2026-09-28): a charge is a destination charge (-> cost inclusion)
only if BOTH checks agree — it's billed in INR, and its charge head isn't
freight. A foreign-currency charge is never a destination charge (e.g. USD
freight, which Maersk invoices sometimes include). When the two checks
disagree (an INR line named like freight) it's left out and flagged to review.
"""
from __future__ import annotations

import re
from typing import Any, Optional

AMOUNT = r"([\d,]+(?:\.\d+)?)"

# (text on the invoice, display name) — first match wins
CARRIERS = [
    ("MAERSK", "Maersk"), ("CORDELIA", "Cordelia"), ("HAPAG", "Hapag-Lloyd"),
    ("MEDITERRANEAN SHIPPING", "MSC"), ("MSC ", "MSC"), ("CMA CGM", "CMA CGM"), ("OCEAN NETWORK EXPRESS", "ONE"),
    ("COSCO", "COSCO"), ("OOCL", "OOCL"), ("EVERGREEN", "Evergreen"), ("YANG MING", "Yang Ming"),
    ("HMM", "HMM"), ("ZIM ", "ZIM"), ("WAN HAI", "Wan Hai"), ("PACIFIC INTERNATIONAL LINES", "PIL"),
    ("X-PRESS FEEDERS", "X-Press Feeders"), ("UNIFEEDER", "Unifeeder"), ("SAMUDERA", "Samudera"),
    ("GOLD STAR", "Gold Star"), ("EMIRATES SHIPPING", "Emirates Shipping"), ("TS LINES", "TS Lines"),
]

BEFORE_TAX = [
    r"Total\s+Base\s+Amount\s+(?:INR\s+)?" + AMOUNT,
    r"Taxable\s+Amount\s*:?\s*(?:INR\s+)?" + AMOUNT,
    r"Total\s+Taxable\s+(?:Value|Amount)\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s*Amount\s*Before\s*Tax\s*:?\s*" + AMOUNT,
    r"Sub\s*-?\s*total\s*:?\s*(?:INR\s+)?" + AMOUNT,
]
GST_TOTAL = [
    r"Total\s+taxes\b[^\n]*?INR\s+" + AMOUNT,
    r"Total\s+(?:GST|Tax)\s*(?:Amount)?\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Tax\s*Amount\s*:?\s*GST\s*:?\s*" + AMOUNT,
]
# one GST component per line, e.g. "SGST (%) 9% INR 12,195" — summed when there's no total-tax line
GST_PART = re.compile(r"^\s*(?:[SCIU]-?GST)\b[^\n]*?(?:INR|Rs\.?|₹)\s*" + AMOUNT + r"\s*$", re.IGNORECASE | re.MULTILINE)
AFTER_TAX = [
    r"Total\s+Payable\s+Amount\s+(?:INR\s+)?" + AMOUNT,
    r"Total\s+Invoice\s+(?:Value|Amount)\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s+Amount\s+After\s+Tax\s*:?\s*" + AMOUNT,
    r"Grand\s+Total\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s+Amount\s*:?\s*(?:INR|Rs\.?|₹)\s*" + AMOUNT,
]
BL_NO = [
    r"Bill\s+of\s+Lading\s*(?:No\.?|Number|#)?\s*:?\s*([A-Z0-9]{6,20})\b",
    r"\bM?HBL\s*#\s*:?\s*([A-Z0-9]{6,20})\b",
    r"\bB/?L\s*(?:No\.?|Number|#)\s*:?\s*([A-Z0-9]{8,20})\b",
]
INVOICE_NO = [r"Invoice\s+(?:Number|No\.?)\s*:?\s*([A-Z0-9/-]{6,})"]

# Maersk: "<desc> <qty> <UOM> <rate> <CUR> <extended> [IN IGST 18% <tax>] <taxable INR>", next line "SAC/HSN 996711"
MAERSK_LINE = re.compile(
    r"^(?P<desc>[A-Za-z][^\n]*?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<uom>[A-Z]{2,5})\s+(?P<rate>[\d,]+\.\d{2})\s+(?P<cur>[A-Z]{3})\s+"
    r"[\d,]+\.\d{2}(?:\s+IN\s+\S+\s+\d+(?:\.\d+)?%\s+(?P<gst>[\d,]+\.\d{2}))?\s+(?P<amount>[\d,]+\.\d{2})\s*$")
# Cordelia: "<qty> <CUR> <rate> <amount> <ex.rate> <amount INR>", next line "<desc> (SAC:996711)"
AMOUNT_FIRST_LINE = re.compile(
    r"^(?P<qty>\d+(?:\.\d+)?)\s+(?P<cur>[A-Z]{3})\s+(?P<rate>[\d,]+(?:\.\d+)?)\s+[\d,]+(?:\.\d+)?\s+[\d.]+\s+(?P<amount>[\d,]+(?:\.\d+)?)\s*$")
SAC_IN_DESC = re.compile(r"\(SAC\s*:?\s*(\d{6})\)")
# charge heads that are freight / origin, not destination charges
FREIGHT_HEAD = re.compile(
    r"FREIGHT|\bBAS\b|\bBAF\b|BUNKER|\bEBS\b|\bCAF\b|CURRENCY\s+ADJ|PEAK\s+SEASON|\bPSS\b|\bGRI\b|"
    r"LOW\s+SULPHUR|\bLSS\b|\bORIGIN\b|EXPORT", re.IGNORECASE)
SAC_LINE = re.compile(r"^SAC(?:/HSN)?\s*:?\s*(\d{6})\s*$")


def _num(raw: Optional[str]) -> Optional[float]:
    try:
        return float(raw.replace(",", "")) if raw else None
    except ValueError:
        return None


def _first(patterns: list[str], text: str) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _charges(lines: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_maersk = False
    for i, line in enumerate(lines):
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        m = MAERSK_LINE.match(line.strip())
        if m:
            seen_maersk = True
            sac = SAC_LINE.match(nxt)
            out.append({"description": m["desc"].strip(), "sac": sac.group(1) if sac else None,
                        "currency": m["cur"], "quantity": _num(m["qty"]), "rate": _num(m["rate"]),
                        "amount": _num(m["amount"]), "gst": _num(m["gst"]) if m["gst"] else 0.0})
            continue
        if seen_maersk:
            continue
        m = AMOUNT_FIRST_LINE.match(line.strip())
        if m and nxt:
            sac = SAC_IN_DESC.search(nxt)
            out.append({"description": SAC_IN_DESC.sub("", nxt).strip(" -"), "sac": sac.group(1) if sac else None,
                        "currency": m["cur"], "quantity": _num(m["qty"]), "rate": _num(m["rate"]),
                        "amount": _num(m["amount"]), "gst": None})
    for c in out:
        inr = c["currency"] == "INR"
        freight_head = bool(FREIGHT_HEAD.search(c["description"] or ""))
        c["in_cost_inclusion"] = inr and not freight_head
        # the two checks disagree -> left out, but worth a look
        c["review"] = inr and freight_head
    return out


def scan_shipping_line_text(text: str) -> dict[str, Any]:
    upper = text.upper()
    before = _num(_first(BEFORE_TAX, text))
    gst = _num(_first(GST_TOTAL, text))
    if gst is None:
        parts = [_num(x) for x in GST_PART.findall(text)]
        gst = sum(p for p in parts if p is not None) if parts else None
    after = _num(_first(AFTER_TAX, text))
    if gst is None and before is not None and after is not None and after >= before:
        gst = round(after - before, 2)
    if before is None and gst is not None and after is not None:
        before = round(after - gst, 2)

    charges = _charges(text.splitlines())
    result: dict[str, Any] = {
        "carrier": next((name for key, name in CARRIERS if key in upper), None),
        "invoice_no": _first(INVOICE_NO, text),
        "is_proforma": "PROFORMA" in upper or "PRO FORMA" in upper,
        "bl_no": _first(BL_NO, text),
        "be_no": None,
        "cfs_before_tax": before,
        "cfs_gst": gst,
        "cfs_after_tax": after,
        "charges": charges,
    }
    result["cfs_sanity_ok"] = None
    if None not in (before, gst, after):
        result["cfs_sanity_ok"] = abs(before + gst - after) < 1.0
    if charges and before is not None:
        # charge lines should add up to the base amount; if not, don't offer them for cost inclusion
        result["charges_complete"] = abs(sum(c["amount"] or 0 for c in charges) - before) < 1.0
    return result

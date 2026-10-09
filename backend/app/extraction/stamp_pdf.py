"""
Stamp duty receipts -> the stamp duty actually paid and the BE it was paid for.

  - Nhava Sheva: MH GRAS e-challan (text PDF)
        "0030046401 Stamp Duty 1492.00" ... "BE NO 3401995 DT 27.08.2026"
        "Amount In One Thousand Four Hundred Ninety Two Rupees Only" / "Total 1,492.00"
  - Mundra: SHCIL Gujarat e-stamp certificate — always a scan, read by OCR (ocr.py)
        "Stamp Duty Amount(Rs.)" "1,372" "(One Thousand Three Hundred And Seventy Two only)"
        "... BE NO: 4042224 DTD: 26/09/2026"

The amount counts only when the figure and the amount in words agree (OCR can drop or
misread a digit; it can't misread both the same way). Returns amount_paid (None when
unread or the two disagree), amount_digits, amount_words, be_no, certificate_no, kind.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "lac": 100000,
           "crore": 10000000, "crores": 10000000}
_VOCAB = sorted(list(_UNITS) + list(_SCALES) + ["and"], key=len, reverse=True)


def words_to_number(words: Optional[str]) -> Optional[int]:
    """'One Thousand Three Hundred And Seventy Two' -> 1372. Spaces optional — OCR often
    runs the words together ('TwoThousandEightHundredAndTwentyThree'). None if any part
    isn't a number word."""
    s = re.sub(r"[^a-z]", "", (words or "").lower())
    if not s:
        return None
    tokens, i = [], 0
    while i < len(s):
        w = next((v for v in _VOCAB if s.startswith(v, i)), None)
        if w is None:
            return None
        tokens.append(w)
        i += len(w)
    total = current = 0
    seen = False
    for w in tokens:
        if w == "and":
            continue
        seen = True
        if w in _UNITS:
            current += _UNITS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        else:
            total += (current or 1) * _SCALES[w]
            current = 0
    return total + current if seen else None


def _amount(raw: Optional[str]) -> Optional[Decimal]:
    """'1,372' / '1492.00' / OCR's '1.035' and '1.668.00' (dots for commas) -> Decimal."""
    if not raw:
        return None
    raw = raw.replace(",", ".").strip(".")
    parts = raw.split(".")
    if len(parts) > 1 and len(parts[-1]) == 2:  # paise
        whole, paise = parts[:-1], parts[-1]
    else:
        whole, paise = parts, None
    if any(len(p) != 3 for p in whole[1:]):  # a dot that isn't a thousands separator
        return None
    try:
        return Decimal("".join(whole) + (f".{paise}" if paise else ""))
    except InvalidOperation:
        return None


_NUMBER_LINE = re.compile(r"^\s*(?:Rs\.?\s*)?([\d][\d.,]*)\s*/?-?\s*$")


def _shcil_figure(text: str) -> Optional[str]:
    """The number on its own line next to 'Stamp Duty Amount(Rs.)' — OCR puts it after the
    label or, on some scans, before it."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"Stamp\s*Duty\s*Amount", line, re.I):
            same = re.search(r"Amount\s*\(?\s*Rs\.?\s*\)?\s*[:|]?\s*([\d][\d.,]*)\s*$", line, re.I)
            if same:
                return same.group(1)
            for j in (i + 1, i - 1, i + 2, i - 2):
                if 0 <= j < len(lines):
                    m = _NUMBER_LINE.match(lines[j])
                    if m:
                        return m.group(1)
    return None


def scan_stamp_text(text: str) -> dict[str, Any]:
    flat = re.sub(r"[ \t]+", " ", text or "")
    upper = flat.upper()
    shcil = "STAMP DUTY AMOUNT" in re.sub(r"\s+", " ", upper) or "STAMPDUTYAMOUNT" in upper.replace(" ", "")
    digits = words = None
    if shcil:
        digits = _shcil_figure(text)
        w = re.search(r"\(\s*([A-Za-z ]+?)\s*only\s*\)?", flat, re.I)
        words = w.group(1) if w else None
    else:  # MH GRAS challan
        m = (re.search(r"\bTotal\s*:?\s*([\d.,]+\.\d{2})", flat)
             or re.search(r"Stamp\s+Duty\s+([\d.,]+\.\d{2})", flat))
        digits = m.group(1) if m else None
        w = re.search(r"Amount\s+In\s+([A-Za-z ]+?)\s+Rupees\s+Only", flat, re.I)
        words = w.group(1) if w else None
    figure, in_words = _amount(digits), words_to_number(words)
    agree = figure is not None and in_words is not None and figure == in_words
    be = re.search(r"\bB\s*E\s*NO\.?\s*[:\-]?\s*(\d{7})\b", flat, re.I) or re.search(r"BENO[:\-]?(\d{7})", upper)
    cert = re.search(r"\b(IN-[A-Z]{2}\d{10,}[A-Z]?)\b", upper)
    grn = re.search(r"\bGRN\s*:?\s*(MH\d{6,}[A-Z0-9]*)", upper)
    return {
        "kind": "shcil" if shcil else "mh_challan",
        "amount_paid": float(figure) if agree else None,
        "amount_digits": float(figure) if figure is not None else None,
        "amount_words": in_words,
        "be_no": be.group(1) if be else None,
        "certificate_no": cert.group(1) if cert else (grn.group(1) if grn else None),
    }


def scan_stamp_pages(pages: list[str]) -> dict[str, Any]:
    """A receipt file can hold several certificates, one a page, often for other BEs too (one
    payment, several jobs). Each page is read on its own; pick_for_be() chooses this job's."""
    certs = [c for c in (dict(scan_stamp_text(p), page=i + 1) for i, p in enumerate(pages))
             if c["amount_digits"] is not None or c["amount_words"] is not None or c["be_no"]]
    out = {"kind": certs[0]["kind"] if certs else None, "certificates": certs}
    out.update(pick_for_be(out, None))
    return out


def pick_for_be(fields: dict, be_no: Optional[str]) -> dict[str, Any]:
    """{amount_paid, be_no, certificate_no} for this BE out of the file's certificates:
    the one(s) printed with this BE; else the only one there is. Several, none for this BE -> no
    amount (typed by hand), and be_no = one it is for, so the 'differs' warning shows."""
    certs = fields.get("certificates") or []
    mine = [c for c in certs if be_no and c["be_no"] == be_no]
    if not mine and len(certs) == 1:
        mine = certs
    if not mine:
        other = next((c["be_no"] for c in certs if c["be_no"]), None)
        return {"amount_paid": None, "be_no": other, "certificate_no": None}
    amounts = [c["amount_paid"] for c in mine]
    return {"amount_paid": None if None in amounts else sum(amounts), "be_no": mine[0]["be_no"],
            "certificate_no": ", ".join(c["certificate_no"] for c in mine if c["certificate_no"]) or None,
            "amount_digits": mine[0]["amount_digits"], "amount_words": mine[0]["amount_words"]}

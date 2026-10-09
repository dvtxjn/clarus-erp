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
    try:
        return Decimal(raw.replace(",", "")) if raw else None
    except InvalidOperation:
        return None


def scan_stamp_text(text: str) -> dict[str, Any]:
    flat = re.sub(r"[ \t]+", " ", text or "")
    upper = flat.upper()
    shcil = "STAMP DUTY AMOUNT" in re.sub(r"\s+", " ", upper) or "STAMPDUTYAMOUNT" in upper.replace(" ", "")
    digits = words = None
    if shcil:
        m = re.search(r"Stamp\s*Duty\s*Amount\s*\(?\s*Rs\.?\s*\)?\s*[:|]?\s*([\d,]+(?:\.\d{1,2})?)", flat, re.I)
        digits = m.group(1) if m else None
        w = re.search(r"\(\s*([A-Za-z ]+?)\s*only\s*\)?", flat, re.I)
        words = w.group(1) if w else None
    else:  # MH GRAS challan
        m = (re.search(r"\bTotal\s*:?\s*([\d,]+\.\d{2})", flat)
             or re.search(r"Stamp\s+Duty\s+([\d,]+\.\d{2})", flat))
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

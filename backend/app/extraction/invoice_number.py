"""
The invoice's own identity — its number (and the GST e-invoice IRN when printed) — so the
same invoice added twice (e.g. once uploaded, once picked from Drive) is counted once
(client, 2026-09-29).

  Navkar tax invoice:  "Invoice No  : PI/DPDI/07609/27"   + "IRN :76fc5c94…" (64 hex)
  Navkar proforma:     "Proforma : TI/IMPE/00530/27"
"""
from __future__ import annotations

import re
from typing import Optional

IRN = re.compile(r"\bIRN\s*(?:No\.?)?\s*[:\-]?\s*([0-9a-f]{64})\b", re.I)
NUMBER = [
    re.compile(r"\b(?:Tax\s+)?Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,})", re.I),
    re.compile(r"\bProforma(?:\s+Invoice)?\s*(?:No\.?|Number)?\s*:\s*([A-Z0-9][A-Z0-9/\-]{4,})", re.I),
    re.compile(r"\bBill\s*(?:No\.?|Number)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,})", re.I),
]


def invoice_identity(text: str) -> dict[str, Optional[str]]:
    irn = IRN.search(text or "")
    number = next((m.group(1) for rx in NUMBER if (m := rx.search(text or ""))), None)
    if number and not re.search(r"\d", number):  # a word, not a number ("Invoice No: Date")
        number = None
    return {"invoice_no": number.strip("/-").upper() if number else None,
            "irn": irn.group(1).lower() if irn else None}

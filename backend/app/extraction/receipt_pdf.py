"""
Payment receipts (shipping line / CFS) -> the amount actually paid.

No client sample yet, so this is best effort: the first of the usual
"amount received / paid" labels, else a "Rupees ... Only" amount line, else the
largest "Total" figure. The amount is editable on the Overview either way.
Returns amount_paid, receipt_no, bl_no, be_no.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.extraction.shipping_line_pdf import AMOUNT, BL_NO, CARRIERS, _first, _num

PAID = [
    r"Amount\s+(?:Received|Paid|Collected)\s*(?:\(\s*(?:INR|Rs\.?|₹)\s*\))?\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"(?:Received|Paid)\s+Amount\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Receipt\s+Amount\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Payment\s+Amount\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s+(?:Amount\s+)?(?:Received|Paid)\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"(?:Rs\.?|INR|₹)\s*" + AMOUNT + r"\s*/?-?\s*\(?\s*(?:Rupees|INR)\b[^\n]*Only",
    r"Grand\s+Total\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
    r"Total\s*:?\s*(?:INR|Rs\.?|₹)?\s*" + AMOUNT,
]
RECEIPT_NO = [r"Receipt\s*(?:No\.?|Number|#)\s*:?\s*([A-Z0-9/-]{4,})"]


def scan_receipt_text(text: str) -> dict[str, Any]:
    upper = text.upper()
    paid: Optional[float] = _num(_first(PAID, text))
    be = re.search(r"\b(?:BOE|BE|Bill\s+of\s+Entry)\s*(?:No\.?|Number)?\s*:?\s*(\d{7})\b", text, re.IGNORECASE)
    return {
        "amount_paid": paid,
        "receipt_no": _first(RECEIPT_NO, text),
        "bl_no": _first(BL_NO, text),
        "be_no": be.group(1) if be else None,
        "carrier": next((name for key, name in CARRIERS if key in upper), None),
    }

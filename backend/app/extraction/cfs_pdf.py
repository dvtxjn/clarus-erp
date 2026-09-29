"""
CFS (Container Freight Station) invoice extraction + BE/CFS classification —
ported from reference/be_expense_sheet.py v7.2 (parse_amount,
extract_cfs_data, match_cfs_to_row, classify_pdf). Patterns and scoring
weights are verbatim.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Sequence, Tuple

import pdfplumber

from app.extraction.be_pdf import PdfSource, read_pdf


def parse_amount(raw: Optional[str]) -> Optional[float]:
    """'1,08,560.00' -> 108560.0 (Indian-style comma grouping)."""
    if not raw:
        return None
    try:
        return float(raw.replace(",", "").strip())
    except ValueError:
        return None


def scan_cfs_text(text: str) -> dict[str, Any]:
    """Label-based (not table-position-based), which is what lets it work
    across CFS operators with different layouts. If a new operator phrases a
    label differently, add a fallback pattern to the lists below."""
    def find_first(patterns):
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    result: dict[str, Any] = {
        "be_no": find_first([r'BOE\s*No\.?\s*:?\s*(\d{5,8})']),
        "bl_no": find_first([r'BL\s*No\.?\s*:?\s*([A-Z0-9]{8,20})']),
        "cfs_before_tax": parse_amount(find_first([
            r'Total\s*Amount\s*Before\s*Tax\s*:?\s*([\d,]+\.?\d*)',
            r'Total\s*Taxable\s*(?:Value|Amount)\s*:?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)',
        ])),
        "cfs_after_tax": parse_amount(find_first([
            r'Total\s*Amount\s*After\s*Tax\s*:?\s*([\d,]+\.?\d*)',
            r'(?:Total\s*Invoice\s*(?:Value|Amount)|Grand\s*Total)\s*:?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)',
        ])),
        "cfs_gst": parse_amount(find_first([
            r'Tax\s*Amount\s*:?\s*GST\s*:?\s*([\d,]+\.?\d*)',
            r'Total\s*(?:GST|Tax)\s*(?:Amount)?\s*:?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)',
        ])),
    }

    # before-tax + GST must equal after-tax: catches a regex that "succeeded"
    # but grabbed the wrong number on an unfamiliar layout.
    result["cfs_sanity_ok"] = None
    if None not in (result["cfs_before_tax"], result["cfs_gst"], result["cfs_after_tax"]):
        result["cfs_sanity_ok"] = abs(
            (result["cfs_before_tax"] + result["cfs_gst"]) - result["cfs_after_tax"]
        ) < 1.0
    return result


def scan_cfs_pdf(source: PdfSource) -> dict[str, Any]:
    try:
        with pdfplumber.open(source) as pdf:
            pages, _ = read_pdf(pdf)
    except Exception as e:
        return {"error": str(e)}
    text = "\n".join(pages)
    return scan_cfs_text(text)


def match_cfs_to_row(cfs: dict, rows: Sequence[dict]) -> Tuple[Optional[int], Optional[str]]:
    """Index of the BE row this CFS invoice belongs to. BE Number first,
    BL Number (row's MAWB) as fallback. Returns (index, matched_by)."""
    cfs_be = (cfs.get("be_no") or "").strip()
    cfs_bl = (cfs.get("bl_no") or "").strip().upper()

    if cfs_be:
        for i, row in enumerate(rows):
            if (row.get("be_no") or "").strip() == cfs_be:
                return i, "BE Number"
    if cfs_bl:
        for i, row in enumerate(rows):
            if (row.get("mawb") or "").strip().upper() == cfs_bl:
                return i, "BL Number"
    return None, None


def classify_text(text: str) -> str:
    """'BE' or 'CFS' by scored label signals; ties / no signal -> 'BE'."""
    upper = text.upper()
    be_score = cfs_score = 0

    if "BILL OF ENTRY" in upper:
        be_score += 3
    if re.search(r'1\.\s*IMPORTER\s+NAME', upper):
        be_score += 3
    if re.search(r'\bIN[A-Z]{3}\d\b', upper):
        be_score += 1
    if "TOT.ASS VAL" in upper or "TOT. AMOUNT" in upper:
        be_score += 2

    if "CONTAINER FREIGHT STATION" in upper:
        cfs_score += 3
    if re.search(r'TOTAL\s*AMOUNT\s*BEFORE\s*TAX', upper):
        cfs_score += 3
    if re.search(r'BOE\s*NO', upper):
        cfs_score += 1
    if re.search(r'\bCFS\b', upper):
        cfs_score += 1

    return "CFS" if cfs_score > be_score else "BE"

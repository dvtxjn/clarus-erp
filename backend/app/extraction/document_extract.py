"""
Read fields out of a document at upload time, by document type:
  - Assessed / OOC / Gatepass Bill of Entry -> the BE fields from be_pdf.py
    (BE no/date, port, MBL/HBL, containers, gross wt, assessable value,
    IGST, total duty) + for OOC copies: OOC date and examination date/time
  - CFS proforma / tax invoice -> BE/BL no and the CFS amounts (cfs_pdf.py)

Never raises: an unreadable PDF just yields {"error": ...}.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional, Tuple

import pdfplumber

from app.core.enums import DocumentType
from app.extraction.be_pdf import normalize_date, read_pdf, scan_be_text
from app.extraction.cfs_pdf import scan_cfs_text
from app.extraction.receipt_pdf import scan_receipt_text
from app.extraction.shipping_line_pdf import scan_shipping_line_text

BE_TYPES = {
    DocumentType.ASSESSED_BILL_OF_ENTRY,
    DocumentType.OOC_BILL_OF_ENTRY,
    DocumentType.GATEPASS_BILL_OF_ENTRY,
}
CFS_TYPES = {DocumentType.CFS_PROFORMA_INVOICE, DocumentType.CFS_TAX_INVOICE}
LINE_TYPES = {DocumentType.SHIPPING_LINE_PROFORMA, DocumentType.SHIPPING_LINE_INVOICE}
RECEIPT_TYPES = {DocumentType.CFS_RECEIPT, DocumentType.SHIPPING_LINE_RECEIPT}
# CFS invoices: cfs_pdf.py; shipping line invoices: shipping_line_pdf.py (per-line layouts)
INVOICE_TYPES = CFS_TYPES | LINE_TYPES

_DATE_WORD = re.compile(r"^\d{2}-(?:\d{2}|[A-Za-z]{3})-\d{2,4}$")  # 10-SEP-26 / 10-09-2026


def parse_ddmmyyyy(value: Optional[str]) -> Optional[date]:
    """'05.03.2026' (normalize_date output) -> date."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _processing_row(words: list, event: str, label_x0: float) -> Tuple[Optional[str], Optional[str]]:
    """(date, time) printed on one row of the BE's 'H. PROCESSING DETAILS'
    table (1.EVENT | 2.DATE | 3.TIME). Blank row -> (None, None)."""
    label = next((w for w in words if w["text"] == event and abs(w["x0"] - label_x0) < 6), None)
    if label is None:
        return None, None
    row = sorted(
        (w for w in words if abs(w["top"] - label["top"]) < 3 and label["x1"] < w["x0"] < label["x1"] + 160),
        key=lambda w: w["x0"],
    )
    for i, w in enumerate(row):
        if _DATE_WORD.match(w["text"]):
            time = None
            if i + 1 < len(row):
                t = re.sub(r"[^0-9:]", "", row[i + 1]["text"])  # watermark letters bleed in, e.g. '17O:46'
                time = t if re.fullmatch(r"\d{1,2}:\d{2}", t) else None
            return w["text"], time
    return None, None


def extract_ooc_details(first_page_words: list, first_page_text: str) -> dict[str, Any]:
    """
    OOC date, and whether the shipment was examined — from the OOC copy's
    'H. PROCESSING DETAILS' table (only present on OOC copies, not assessed):

        1.EVENT      2.DATE      3.TIME
        Submission   31-AUG-26   17:43
        Assessment   31-AUG-26   17:46
        Examination  10-SEP-26   16:27    <- blank when not examined
        OOC          10-09-2026  16:40

    Read by word position, because the page's plain text is scrambled by the
    'OOC COPY' watermark. The Examination row having a date = examined.
    """
    anchor = next((w for w in first_page_words if w["text"] == "Submission"), None)
    exam_date = exam_time = ooc_date = None
    if anchor is not None:
        exam_date, exam_time = _processing_row(first_page_words, "Examination", anchor["x0"])
        ooc_date, _ = _processing_row(first_page_words, "OOC", anchor["x0"])
    if not ooc_date:  # fallback: the 'OOC DATE 10-09-2026' line
        m = re.search(r"OOC\s*DATE\s*(\d{2}[-/.]\d{2}[-/.]\d{4})", first_page_text)
        ooc_date = m.group(1) if m else None
    return {
        "ooc_date": normalize_date(ooc_date) if ooc_date else None,
        "under_examination": exam_date is not None if anchor is not None else None,
        "examination_at": " ".join(x for x in (exam_date, exam_time) if x) or None,
    }


def extract_document_fields(document_type: DocumentType, path: str) -> dict[str, Any]:
    if document_type not in BE_TYPES | INVOICE_TYPES | RECEIPT_TYPES:
        return {}
    try:
        with pdfplumber.open(path) as pdf:
            pages, words = read_pdf(pdf)
    except Exception as e:  # not a PDF / encrypted / corrupt
        return {"error": f"Couldn't read PDF: {e}"}

    text = "\n".join(pages)
    if document_type in LINE_TYPES:
        return scan_shipping_line_text(text)
    if document_type in RECEIPT_TYPES:
        return scan_receipt_text(text)
    if document_type in INVOICE_TYPES:
        return scan_cfs_text(text)

    fields = scan_be_text(text, words)
    # ICEGATE prints "OOC COPY" on the out-of-charge copy (page header + watermark).
    # None = no readable text (e.g. a scan), so we can't tell.
    fields["is_ooc_copy"] = ("OOC COPY" in text.upper()) if text.strip() else None
    if document_type == DocumentType.OOC_BILL_OF_ENTRY or fields["is_ooc_copy"]:
        fields.update(extract_ooc_details(words, pages[0] if pages else ""))
    return fields

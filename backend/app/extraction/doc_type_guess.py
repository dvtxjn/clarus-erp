"""
What a PDF in a shipment's Drive folder is: first from its file name (same rules as
frontend/src/docTypeGuess.ts), then — when the name says nothing — from the words on
its first page. None = unsure; the user marks it.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import pdfplumber

from app.core.enums import DocumentType as T

# Order matters: more specific first.
NAME_RULES: list[tuple[str, T]] = [
    (r"\bOOC\b|OUT OF CHARGE", T.OOC_BILL_OF_ENTRY),
    (r"GATE ?PASS", T.GATEPASS_BILL_OF_ENTRY),
    (r"ASSESS|\bBOE\b|\bB\.?E\.?\b|BILL OF ENTRY", T.ASSESSED_BILL_OF_ENTRY),
    (r"CFS.*(RCPT|RECEIPT)|CFS-RCPT", T.CFS_RECEIPT),
    (r"CFSTI|CFS.*(TAX|\bTI\b)", T.CFS_TAX_INVOICE),
    (r"CFSPI|CFS.*(PRO|\bPI\b)", T.CFS_PROFORMA_INVOICE),
    (r"SL-RCPT|(\bSL\b|LINER|LINE).*(RCPT|RECEIPT)", T.SHIPPING_LINE_RECEIPT),
    (r"SL-PI|(\bSL\b|LINER|DSC|DESTINATION).*(PRO|\bPI\b)", T.SHIPPING_LINE_PROFORMA),
    (r"SL-DSC|\bDSC\b|LINER INV|DESTINATION CHARGE", T.SHIPPING_LINE_INVOICE),
    (r"DO.{0,3}EMPTY|EMPTY.{0,3}DO", T.DO_EMPTY_LETTER),
    (r"\bDO\b|DELIVERY ORDER", T.DO_LETTER),
    (r"EMPTY", T.EMPTY_LETTER),
    (r"\bHBL\b", T.HBL_COPY),
    (r"\bMBL\b|\bBL\b|\bB/L\b|BILL OF LADING", T.BL_COPY),
    (r"COMMERCIAL|\bC\.?I\.?\b|\bINV(OICE)?\b", T.COMMERCIAL_INVOICE),
    (r"PACKING|\bPL\b", T.PACKING_LIST),
    (r"INSUR|\bINS\b", T.INSURANCE),
    (r"STAMP", T.STAMP_DUTY),
    (r"\bHSS\b|HIGH SEA", T.HSS_AGREEMENT),
    (r"FTA|AIFTA|ASEAN", T.FTA_CERTIFICATE_OF_ORIGIN),
    (r"\bCOO\b|CERTIFICATE OF ORIGIN", T.CERTIFICATE_OF_ORIGIN),
    (r"FORM ?6|FORM ?9", T.FORM_6_9),
]

# First-page wording, when the file name is something like "scan0012.pdf"
TEXT_RULES: list[tuple[str, T]] = [
    (r"OOC COPY|OUT OF CHARGE", T.OOC_BILL_OF_ENTRY),
    (r"GATE ?PASS", T.GATEPASS_BILL_OF_ENTRY),
    (r"BILL OF ENTRY FOR (HOME CONSUMPTION|WAREHOUSING)", T.ASSESSED_BILL_OF_ENTRY),
    (r"HIGH SEAS? SALE", T.HSS_AGREEMENT),
    (r"DELIVERY ORDER", T.DO_LETTER),
    (r"PACKING LIST", T.PACKING_LIST),
    (r"CERTIFICATE OF ORIGIN", T.CERTIFICATE_OF_ORIGIN),
    (r"BILL OF LADING", T.BL_COPY),
    (r"COMMERCIAL INVOICE", T.COMMERCIAL_INVOICE),
    (r"INSURANCE (POLICY|CERTIFICATE)", T.INSURANCE),
]


def guess_from_name(file_name: str) -> Optional[T]:
    name = re.sub(r"\.pdf$", "", file_name or "", flags=re.I).replace("_", " ").upper()
    return next((t for pattern, t in NAME_RULES if re.search(pattern, name)), None)


def guess_from_content(data: bytes) -> Optional[T]:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:  # noqa: BLE001 — not a PDF / password-protected / damaged
        return None
    text = re.sub(r"\s+", " ", text.upper())
    return next((t for pattern, t in TEXT_RULES if re.search(pattern, text)), None)

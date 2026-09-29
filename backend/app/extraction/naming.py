"""
Document auto-naming (spec §3.2 — confirmed with client).

Two states depending on whether BE has been filed yet:
  - Before BE filed:  "{DOC_TYPE} - {BL_NUMBER}"
  - After BE filed:   "{DOC_TYPE} - {BL_NUMBER} - {BE_NUMBER}"

NOTE (spec §6, item #2): the exact abbreviation token per document type is
still open — client has 2 existing Python scripts encoding the canonical
list, not yet shared. DOC_TYPE_ABBREVIATIONS below is a reasonable-default
placeholder; swap in the real list once those scripts are shared, per the
spec's suggested default.
"""
from __future__ import annotations
import re
from app.core.enums import DocumentType

DOC_TYPE_ABBREVIATIONS = {
    DocumentType.CFS_PROFORMA_INVOICE: "CFSPI",
    DocumentType.CFS_TAX_INVOICE: "CFSTI",
    DocumentType.ASSESSED_BILL_OF_ENTRY: "ASSESSED",
    DocumentType.OOC_BILL_OF_ENTRY: "OOC",
    DocumentType.GATEPASS_BILL_OF_ENTRY: "GATEPASS",
    DocumentType.BL_COPY: "BL",
    DocumentType.HBL_COPY: "HBL",
    DocumentType.COMMERCIAL_INVOICE: "CI",
    DocumentType.PACKING_LIST: "PL",
    DocumentType.INSURANCE: "INS",
    DocumentType.SHIPPING_LINE_INVOICE: "SL-DSC",
    DocumentType.SHIPPING_LINE_PROFORMA: "SL-PI",
    DocumentType.SHIPPING_LINE_RECEIPT: "SL-RCPT",
    DocumentType.CFS_RECEIPT: "CFS-RCPT",
    DocumentType.DO_LETTER: "DO",
    DocumentType.EMPTY_LETTER: "EMPTY",
    DocumentType.DO_EMPTY_LETTER: "DO-EMPTY",
    DocumentType.HSS_AGREEMENT: "HSS",
    DocumentType.STAMP_DUTY: "STAMP",
    DocumentType.HSS_STAMP_DUTY: "HSS",
    DocumentType.CERTIFICATE_OF_ORIGIN: "COO",
    DocumentType.FTA_CERTIFICATE_OF_ORIGIN: "FTACOO",
    DocumentType.FORM_6_9: "FORM6-9",
    DocumentType.FORM_6: "FORM6",
    DocumentType.FORM_9: "FORM9",
    DocumentType.OTHER: "DOC",
}

_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')


def _clean(value: str) -> str:
    return _ILLEGAL_FILENAME_CHARS.sub("", value).strip()


def generate_document_filename(
    document_type: DocumentType,
    bl_number: str,
    be_number: str | None,
) -> str:
    """
    Implements the two-state naming rule from spec §3.2. Returns just the
    base name (no extension) — caller appends ".pdf".
    """
    doc_abbrev = DOC_TYPE_ABBREVIATIONS.get(document_type, "DOC")
    bl_clean = _clean(bl_number) if bl_number else "UNKNOWN_BL"

    if be_number:
        return f"{doc_abbrev} - {bl_clean} - {_clean(be_number)}"
    return f"{doc_abbrev} - {bl_clean}"

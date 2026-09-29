"""
Is a PDF digital (has a text layer the ERP can read) or scanned (pictures of pages —
nothing can be read until OCR is added)? Client, 2026-09-29: show it on every document.

    digital  every page has text      -> details are read automatically
    partly   some pages are scans     -> only the text pages are read
    scanned  no page has text         -> nothing can be read (needs a digital copy / OCR)
    unreadable  not a valid PDF
"""
from __future__ import annotations

import pdfplumber

MIN_CHARS = 25  # a page with fewer readable characters is treated as a scan (stamps, page numbers)
MAX_PAGES = 30


def pdf_kind(path: str) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages[:MAX_PAGES]
            if not pages:
                return "unreadable"
            text_pages = sum(1 for p in pages if len((p.extract_text() or "").strip()) >= MIN_CHARS)
    except Exception:  # noqa: BLE001 — corrupt / encrypted / not a PDF
        return "unreadable"
    if text_pages == len(pages):
        return "digital"
    return "scanned" if text_pages == 0 else "partly"

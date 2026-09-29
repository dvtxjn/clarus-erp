"""
Mixed-batch scan (spec §5.1): a single upload of BE + CFS PDFs is classified
per file, BE fields extracted, CFS invoices matched to their BE row, and each
row checked against the AD-code registry and for duplicate BE numbers —
the same pipeline the reference tool's main() + open_batch_table() ran.
"""
from __future__ import annotations

from typing import BinaryIO, Iterable, Mapping, Optional, Tuple

import pdfplumber

from app.extraction.be_pdf import CRITICAL_BE_FIELDS, read_pdf, scan_be_text
from app.extraction.cfs_pdf import classify_text, match_cfs_to_row, scan_cfs_text
from app.extraction.excel_imports import importer_name_check


def _read_pdf(source: BinaryIO) -> Tuple[str, list, str]:
    """(full text, page-1 words, first-two-pages text for classification)."""
    with pdfplumber.open(source) as pdf:
        page_texts, words = read_pdf(pdf)
    return "\n".join(page_texts), words, "\n".join(page_texts[:2])


def scan_batch(files: Iterable[Tuple[str, BinaryIO]],
               org_registry: Mapping[str, str],
               existing_be_numbers: Mapping[str, int]) -> dict:
    """files: (filename, binary stream). existing_be_numbers: {be_no: shipment_id}
    for 'previously processed' detection. Returns dict matching BatchScanOut."""
    rows, cfs_scans = [], []
    seen_be: set = set()

    for filename, stream in files:
        try:
            text, words, head = _read_pdf(stream)
        except Exception as e:
            rows.append({"filename": filename, "error": f"Could not read PDF: {e}"})
            continue

        if classify_text(head) == "CFS":
            cfs_scans.append({"filename": filename, **scan_cfs_text(text)})
            continue

        row = {"filename": filename, **scan_be_text(text, words)}
        row["missing"] = [f for f in CRITICAL_BE_FIELDS if not row.get(f)]
        row["name_mismatch"], row["billing_name"] = importer_name_check(
            row.get("ad_code"), row.get("importer_name"), org_registry)
        be_no: Optional[str] = row.get("be_no")
        if be_no:
            row["duplicate_in_batch"] = be_no in seen_be
            seen_be.add(be_no)
            row["existing_shipment_id"] = existing_be_numbers.get(be_no)
        rows.append(row)

    unmatched = []
    for cfs in cfs_scans:
        idx, by = match_cfs_to_row(cfs, rows)
        if idx is None or rows[idx].get("cfs"):
            unmatched.append(cfs)
        else:
            cfs.update(matched_row=idx, matched_by=by)
            rows[idx]["cfs"] = cfs
    return {"rows": rows, "unmatched_cfs": unmatched}

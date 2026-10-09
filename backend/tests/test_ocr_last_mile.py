"""OCR is the last mile (client, 2026-10-09): digital text is the source; a scan with no text is read by OCR,
marked as such, only fills blanks, and its amounts count only when they cross-check."""
import pdfplumber

import app.extraction.ocr as ocr_mod
from tests.conftest import be_pdf, cfs_pdf, make_pdf
from tests.test_document_sync import _new_shipment, _upload


def _text(pdf) -> str:
    with pdfplumber.open(pdf) as p:
        return "\n".join(pg.extract_text() or "" for pg in p.pages)


def _scan_reads_as(monkeypatch, pdf):
    """A blank (image-only) PDF whose OCR gives this PDF's text."""
    text = _text(pdf)
    calls = []
    monkeypatch.setattr(ocr_mod, "ocr_text", lambda path, timeout=90: calls.append(path) or text)
    return make_pdf([]), calls


def test_digital_file_never_uses_ocr(client, admin_headers, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr_mod, "ocr_text", lambda path, timeout=90: calls.append(path))
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())
    assert calls == [] and "ocr" not in doc["extraction"]["fields"]


def test_scanned_cfs_invoice_that_adds_up_is_used_and_marked(client, admin_headers, monkeypatch):
    scan, calls = _scan_reads_as(monkeypatch, cfs_pdf())
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", scan)
    assert calls and doc["extraction"]["fields"]["ocr"] is True
    assert float(doc["amount_total"]) == 128100.80
    assert any("read by OCR" in n for n in doc["extraction"]["notes"])


def test_scanned_cfs_invoice_that_doesnt_add_up_is_not_used(client, admin_headers, monkeypatch):
    scan, _ = _scan_reads_as(monkeypatch, cfs_pdf(after="1,28,700.80"))  # a misread digit
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", scan)
    f = doc["extraction"]["fields"]
    assert f["ocr"] is True and f["ocr_unverified"] is True
    assert doc["amount_total"] is None and doc["amount_before_tax"] is None
    assert any("don't add up — not used" in n for n in doc["extraction"]["notes"])


def test_scanned_be_fills_blanks_but_never_overwrites(client, admin_headers, monkeypatch):
    sid = _new_shipment(client, admin_headers)
    _upload(client, admin_headers, sid, "assessed_bill_of_entry", be_pdf(be_no="5550009"))  # digital: duty 61,500
    scan, _ = _scan_reads_as(monkeypatch, be_pdf(be_no="5550009", tot="91500.00"))  # OCR misread
    doc = _upload(client, admin_headers, sid, "ooc_bill_of_entry", scan)
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert float(s["duty_amount"]) == 61500.0  # the digital reading stands
    assert any("differs from the tracker" in n for n in doc["extraction"]["notes"])


def test_ocr_that_fails_says_enter_by_hand(client, admin_headers, monkeypatch):
    monkeypatch.setattr(ocr_mod, "ocr_text", lambda path, timeout=90: None)
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", make_pdf([]))
    assert doc["amount_total"] is None
    assert any("OCR couldn't read it" in n for n in doc["extraction"]["notes"])

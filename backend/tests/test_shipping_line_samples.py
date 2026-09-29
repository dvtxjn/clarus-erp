"""Shipping line invoices from 12 lines / agents (client samples, 2026-09-30). The PDFs live in
reference/shipping_line_samples (not in git — client data); these tests run when they're there.
Each must read: totals that add up (taxable + GST = total), and charge lines that add up to
the taxable amount, so the cost inclusion can use them."""
from pathlib import Path

import pytest

from app.core.enums import DocumentType
from app.extraction.document_extract import extract_document_fields
from app.extraction.shipping_line_pdf import scan_shipping_line_text

SAMPLES = Path(__file__).resolve().parents[2] / "reference" / "shipping_line_samples"

# file: (carrier, before tax, GST, total, number of charge lines, proforma/draft?)
EXPECTED = {
    "01-cmacgm": ("CMA CGM", 208450.0, 37521.0, 245971.0, 6, False),
    "02-hapag": ("Hapag-Lloyd", 32152.0, 5787.36, 37939.36, 5, False),
    "03-hmm-proforma": ("HMM", 216036.6, 38886.59, 254923.19, 7, True),
    "04-hmm": ("HMM", 216036.6, 38886.59, 254923.19, 7, False),
    "05-maersk": ("Maersk", 26260.0, 4726.8, 30986.8, 3, False),
    "06-emirates": ("Emirates Shipping", 146500.0, 26370.0, 172870.0, 4, True),
    "07-seastar": ("Seastar (Parekh)", 147850.0, 26613.0, 174463.0, 6, True),
    "08-goodrich-a": ("Goodrich Maritime", 110400.0, 19872.0, 130272.0, 8, True),
    "09-goodrich-b": ("Goodrich Maritime", 110400.0, 19872.0, 130272.0, 8, False),
    "10-navio-proforma": ("Navio Shipping", 100500.0, 18090.0, 118590.0, 4, True),
    "11-cordelia-proforma": ("Cordelia", 135500.0, 24390.0, 159890.0, 9, True),
    "12-cordelia-b": ("Cordelia", 137100.0, 24678.0, 161778.0, 10, False),
    "13-msc": ("MSC", 21538.0, 3876.84, 25414.84, 5, False),
    "14-one": ("ONE", 25065.0, 4511.7, 29576.7, 5, False),
}


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="client sample invoices not on this machine")
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_invoice_reads(name):
    carrier, before, gst, after, n, proforma = EXPECTED[name]
    r = extract_document_fields(DocumentType.SHIPPING_LINE_INVOICE, str(SAMPLES / f"{name}.pdf"))
    assert (r["carrier"], r["cfs_before_tax"], r["cfs_gst"], r["cfs_after_tax"]) == (carrier, before, gst, after)
    assert r["cfs_sanity_ok"] and r["is_proforma"] is proforma
    assert len(r["charges"]) == n and r["charges_complete"] is True
    assert r["bl_no"]
    assert all(c["description"] and not c["description"].upper().startswith("CODE") for c in r["charges"])


def test_generic_charge_lines_and_totals():
    """Layouts without a dedicated rule: SAC + an amount followed by its GST %, and a totals row."""
    text = "\n".join([
        "Import THC 40` 996711 5 INR 21,000.00 105000.00 18 18900.00 123,900.00",
        "DO Fees 996719 1 INR 6,000.00 6000.00 18 1080.00 7,080.00",
        "TERMINAL HANDLING - DISCHARGE",
        "PORT 996711 5 20,000.00 INR 1.0000 100,000.00 100,000.00 100,000.00 18 18,000.00 0 0.00 0 0.00",
        "EQUIPMENT SURCHARGE 996799 1 x 1,900 INR 1,900.00 1.00 1,900.00 9.0 171.00 9.0 171.00 0.0 0.00",
        "TSD TERMINAL SECURITY CHARGE (ISPS) USD BX 10.00 7 996719 6,760.60 18 1,216.91 82.60 7,977.51",
        "998538 16,000.00 9 1,440.00 9 1,440.00",
        "213,660.60 38,537.91 252,198.51",
    ])
    r = scan_shipping_line_text(text)
    got = {c["description"]: (c["amount"], c["gst"], c["currency"], c["in_cost_inclusion"]) for c in r["charges"]}
    assert got["Import THC"] == (105000.0, 18900.0, "INR", True)
    assert got["DO Fees"] == (6000.0, 1080.0, "INR", True)
    assert got["TERMINAL HANDLING - DISCHARGE PORT"] == (100000.0, 18000.0, "INR", True)   # wrapped name
    assert got["EQUIPMENT SURCHARGE"] == (1900.0, 342.0, "INR", True)                     # CGST + SGST, ex-rate column
    assert got["TSD TERMINAL SECURITY CHARGE (ISPS)"][2:] == ("USD", True)                 # not Maersk: destination anyway
    assert len(got) == 5                                                                  # the SAC summary row isn't a charge
    assert (r["cfs_before_tax"], r["cfs_gst"], r["cfs_after_tax"]) == (213660.6, 38537.91, 252198.51)


def test_bl_must_match_the_shipment():
    """Client, 2026-09-30: the invoice's BL must be the shipment's MBL or HBL; if not, it's flagged
    and not counted in the shipping line totals."""
    from types import SimpleNamespace

    from app.extraction.cfs_totals import bl_mismatch, line_invoices_counted

    ship = SimpleNamespace(mbl="HLCUBSC2605BTVE6", hbl="SPL2606019")

    def doc(i, bl):
        return SimpleNamespace(id=i, shipment=ship, document_type=DocumentType.SHIPPING_LINE_INVOICE,
                               extraction={"fields": {"bl_no": bl, "invoice_no": f"INV{i}"}})

    right, hbl, other, unknown = doc(1, "HLCUBSC2605BTVE6"), doc(2, "SPL 2606019"), doc(3, "MEDUBY664691"), doc(4, None)
    assert [bl_mismatch(d) for d in (right, hbl, other, unknown)] == [False, False, True, False]
    assert [d.id for d in line_invoices_counted([right, hbl, other, unknown])] == [1, 2, 4]

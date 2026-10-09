"""Stamp duty (client, 2026-10-09): the amount on the receipt (MH challan / Mundra SHCIL certificate,
always a scan -> OCR) must equal what the ERP works out, and the invoice's Stamp Duty line must be it."""
from app.extraction.stamp_pdf import scan_stamp_text, words_to_number
from tests.conftest import make_pdf
from tests.test_invoice import _setup

# what OCR gives for a Mundra certificate: one text line per line, words often run together
SHCIL_OCR = """Certificate No.
IN-GJ78428735484391Y
Stamp Duty Paid By
DEVINE INDUSTRIES
Stamp Duty Amount(Rs.)
2,823
(TwoThousandEightHundredAndTwentyThreeonly)
-540619BENO:4041785DTD:26/09/2026"""


def test_words_to_number():
    assert words_to_number("One Thousand Three Hundred And Seventy Two") == 1372
    assert words_to_number("TwoThousandEightHundredAndTwentyThree") == 2823
    assert words_to_number("Five Hundred And Ninety Six") == 596
    assert words_to_number("One Lakh Two Thousand Fourteen") == 102014
    assert words_to_number("Seven Hundred Sixty") == 760
    assert words_to_number("Rupees garbled") is None


def test_shcil_certificate():
    f = scan_stamp_text(SHCIL_OCR)
    assert f["kind"] == "shcil" and f["amount_paid"] == 2823 and f["be_no"] == "4041785"
    assert f["certificate_no"] == "IN-GJ78428735484391Y"
    # OCR misread a digit: figure and words disagree -> not taken
    f = scan_stamp_text(SHCIL_OCR.replace("2,823", "2,828"))
    assert f["amount_paid"] is None and f["amount_digits"] == 2828 and f["amount_words"] == 2823


def test_mh_challan():
    text = ("0030046401 Stamp Duty 1492.00 Road/Street\nBE NO 3401995 DT 27.08.2026 AC MAHRISHI\n"
            "Amount In One Thousand Four Hundred Ninety Two Rupees Only\nTotal 1,492.00 Words\nGRN MH009780025202627U")
    f = scan_stamp_text(text)
    assert f["kind"] == "mh_challan" and f["amount_paid"] == 1492 and f["be_no"] == "3401995"


def _challan(amount: int, words: str, be_no="7770001"):
    return make_pdf([(40, 40, f"0030046401 Stamp Duty {amount}.00"), (40, 60, f"BE NO {be_no} DT 05.03.2026"),
                     (40, 80, f"Amount In {words} Rupees Only"), (40, 100, f"Total {amount:,}.00 Words")])


def test_reimbursement_invoice_waits_for_matching_stamp_duty(client, admin_headers):
    h = admin_headers
    sid = _setup(client, h)  # Nhava Sheva: AV 2,50,000 + OOC duty 61,500 -> stamp duty CEILING(311.5) = 312
    client.post("/organizations", json={"name": "EARTHMAN", "gstin": "27AACCB2783N1ZA"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    ri = next(i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json() if i["kind"] == "reimbursement")
    assert next(ln for ln in ri["lines"] if ln["code"] == "SD")["non_gst_value"] == "312.00"
    client.patch(f"/final-invoices/{ri['id']}", json={"customer": {**ri["customer"], "gstin": "27AACCB2783N1ZA"}}, headers=h)
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["stamp_duty"]["due"] == "312" and s["stamp_duty"]["receipt_id"] is None

    r = client.post(f"/final-invoices/{ri['id']}/issue", headers=h)
    assert r.status_code == 400 and "Stamp duty receipt not attached" in r.json()["detail"]

    # receipt says 300: doesn't match the calculation -> flagged on upload, invoice blocked
    doc = client.post(f"/shipments/{sid}/documents", data={"document_type": "stamp_duty"},
                      files={"file": ("stamp.pdf", _challan(300, "Three Hundred"), "application/pdf")}, headers=h).json()
    assert float(doc["amount_total"]) == 300
    assert any("doesn't match the calculated" in n for n in doc["extraction"]["notes"])
    r = client.post(f"/final-invoices/{ri['id']}/issue", headers=h)
    assert r.status_code == 400 and "doesn't match the calculated" in r.json()["detail"]

    # corrected by hand to what was really paid -> issues
    assert client.patch(f"/shipments/{sid}/documents/{doc['id']}/amounts",
                        json={"amount_before_tax": "312", "gst_amount": "0"}, headers=h).status_code == 200
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["stamp_duty"]["paid"] == "312.00" and s["stamp_duty"]["edited"] is True
    r = client.post(f"/final-invoices/{ri['id']}/issue", headers=h)
    assert r.status_code == 200, r.json()


def test_receipt_for_another_be_blocks(client, admin_headers):
    h = admin_headers
    sid = _setup(client, h)
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    ri = next(i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json() if i["kind"] == "reimbursement")
    client.patch(f"/final-invoices/{ri['id']}", json={"customer": {**ri["customer"], "gstin": "27AACCB2783N1ZA"}}, headers=h)
    client.post(f"/shipments/{sid}/documents", data={"document_type": "stamp_duty"},
                files={"file": ("stamp.pdf", _challan(312, "Three Hundred Twelve", be_no="1234567"), "application/pdf")},
                headers=h)
    r = client.post(f"/final-invoices/{ri['id']}/issue", headers=h)
    assert r.status_code == 400 and "BE 1234567" in r.json()["detail"]


def test_ocr_number_quirks_and_label_order():
    # figure above its label, dots for commas
    f = scan_stamp_text("Stamp Duty Paid By\n973\nStamp Duty Amount(Rs.)\n(Nine Hundred And Seventy Three only)\nBE NO: 3522039")
    assert f["amount_paid"] == 973
    f = scan_stamp_text("Stamp Duty Amount(Rs.)\n1.035\n(One Thousand And Thirty Five only)")
    assert f["amount_paid"] == 1035
    f = scan_stamp_text("Amount In\nOne Thousand Six Hundred Sixty Eight Rupees Only\nTotal\n1.668.00 words")
    assert f["amount_paid"] == 1668


def test_file_with_several_certificates_picks_this_be():
    from app.extraction.stamp_pdf import pick_for_be, scan_stamp_pages
    page = "Stamp Duty Amount(Rs.)\n{n}\n({w} only)\nBENO:{be}DTD:26/09/2026"
    f = scan_stamp_pages([page.format(n="1,987", w="One Thousand Nine Hundred And Eighty Seven", be="3323824"),
                          page.format(n="1,592", w="One Thousand Five Hundred And Ninety Two", be="3332286")])
    assert len(f["certificates"]) == 2
    assert pick_for_be(f, "3332286")["amount_paid"] == 1592
    assert pick_for_be(f, "3323824")["amount_paid"] == 1987
    other = pick_for_be(f, "9999999")  # none for this BE: typed by hand, warned
    assert other["amount_paid"] is None and other["be_no"] == "3323824"

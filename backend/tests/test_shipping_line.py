"""Shipping line destination-charges invoices: reading, and what counts as cost inclusion
(client rule: billed in INR AND not a freight charge head). Text follows the client's
Maersk tax invoice and Cordelia proforma samples."""
from app.extraction.shipping_line_pdf import scan_shipping_line_text
from tests.conftest import make_pdf

MAERSK = """Tax Invoice
Invoice Number HR27IN3500038423
Bill of Lading 274014260
Terminal Handling Service - Destination 10 CNT 15,750.00 INR 157,500.00 IN IGST 18% 28,350.00 157,500.00
SAC/HSN 996711
Inland Haulage Import 10 CNT 90,055.00 INR 900,550.00 IN IGST 18% 162,099.00 900,550.00
SAC/HSN 996519
Basic Ocean Freight 10 CNT 1,200.00 USD 12,000.00 1,054,800.00
Total Base Amount INR 2,112,850.00
I-GST Total taxes (see tax specification) INR 190,449.00
Total Payable Amount INR 2,303,299.00
Maersk Line India Pvt. Ltd."""

CORDELIA = """Cordelia Container Shipping Line Private Limited
Proforma Invoice
HBL # : CSX26JEDNSA021814
5 INR 23,180 115,900 1.0 115,900
THC- TERMINAL HANDLING CHARGES - NSFT (SAC:996711)
1 INR 5,500 5,500 1.0 5,500
DELIVERY ORDER FEE (DO) (SAC:996713)
1 INR 14,100 14,100 1.0 14,100
BAF - BUNKER ADJUSTMENT (SAC:996521)
Subtotal INR 135,500
Taxable Amount 135,500
SGST (%) 9% INR 12,195
CGST (%) 9% INR 12,195
Total Amount INR 159,890"""


def test_maersk_totals_and_currency_rule():
    r = scan_shipping_line_text(MAERSK)
    assert (r["carrier"], r["invoice_no"], r["bl_no"], r["is_proforma"]) == ("Maersk", "HR27IN3500038423", "274014260", False)
    assert (r["cfs_before_tax"], r["cfs_gst"], r["cfs_after_tax"], r["cfs_sanity_ok"]) == (2112850.0, 190449.0, 2303299.0, True)
    c = {x["description"]: x for x in r["charges"]}
    assert r["charges_complete"] is True
    assert c["Inland Haulage Import"]["in_cost_inclusion"] is True            # INR destination charge
    assert c["Basic Ocean Freight"]["currency"] == "USD"
    assert c["Basic Ocean Freight"]["in_cost_inclusion"] is False              # foreign currency
    assert c["Basic Ocean Freight"]["amount"] == 1054800.0                     # INR value


def test_cordelia_gst_parts_and_freight_head_in_inr():
    r = scan_shipping_line_text(CORDELIA)
    assert (r["carrier"], r["bl_no"], r["is_proforma"]) == ("Cordelia", "CSX26JEDNSA021814", True)
    assert (r["cfs_before_tax"], r["cfs_gst"], r["cfs_after_tax"]) == (135500.0, 24390.0, 159890.0)
    baf = next(x for x in r["charges"] if x["description"].startswith("BAF"))
    # not Maersk (client, 2026-09-30): the import invoice only has destination charges — BAF counts too
    assert (baf["in_cost_inclusion"], baf["review"]) == (True, False)


def test_cost_inclusion_default_override_and_reset(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "274014260SL", "consignee": "Earthman - Mahrishi"}, headers=h).json()["id"]
    pdf = make_pdf([(30, 20 + 12 * i, line) for i, line in enumerate(MAERSK.replace("274014260", "274014260SL").splitlines())])
    up = client.post(f"/shipments/{sid}/documents", data={"document_type": "shipping_line_invoice"},
                     files={"file": ("maersk.pdf", pdf, "application/pdf")}, headers=h).json()
    notes = " ".join(up["extraction"]["notes"])
    assert "Basic Ocean Freight" in notes
    doc_id = up["document"]["id"] if "document" in up else up["id"]
    s = client.get(f"/shipments/{sid}", headers=h).json()
    # THC + haulage (INR) only; GST from the lines
    assert float(s["line_amount_before_tax"]) == 1058050.0 and float(s["line_gst_amount"]) == 190449.0

    r = client.patch(f"/shipments/{sid}/documents/{doc_id}/cost-inclusion", json={"excluded": [1, 2]}, headers=h)
    assert r.status_code == 200 and r.json()["cost_excluded"] == [1, 2]
    assert float(client.get(f"/shipments/{sid}", headers=h).json()["line_amount_before_tax"]) == 157500.0

    r = client.patch(f"/shipments/{sid}/documents/{doc_id}/cost-inclusion",
                     json={"before_tax": "100000", "gst": "18000"}, headers=h).json()
    assert r["cost_manual"] is True
    assert float(client.get(f"/shipments/{sid}", headers=h).json()["line_amount_total"]) == 118000.0

    client.patch(f"/shipments/{sid}/documents/{doc_id}/cost-inclusion", json={"reset": True}, headers=h)
    assert float(client.get(f"/shipments/{sid}", headers=h).json()["line_amount_before_tax"]) == 1058050.0


def test_customs_duty_from_ooc_copy_without_challan(client, admin_headers):
    from tests.test_invoice import _setup
    h = admin_headers
    sid = _setup(client, h, port_consignee="Divine")
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
    assert inv["customs_duty"]["source"] == "ooc" and float(inv["customs_duty"]["total"]) == 61500.0


def _upload(client, h, sid, doc_type, lines):
    pdf = make_pdf([(30, 20 + 12 * i, line) for i, line in enumerate(lines)])
    return client.post(f"/shipments/{sid}/documents", data={"document_type": doc_type},
                       files={"file": ("x.pdf", pdf, "application/pdf")}, headers=h).json()


def test_receipts_and_line_proforma_until_tax_invoice(client, admin_headers):
    from app.extraction.receipt_pdf import scan_receipt_text
    assert scan_receipt_text("Receipt No: R-1001\nAmount Received: INR 1,59,890.00")["amount_paid"] == 159890.0
    assert scan_receipt_text("Received with thanks Rs. 47,200.00 (Rupees Forty Seven Thousand Two Hundred Only)")[
        "amount_paid"] == 47200.0

    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "CSXRCPT0001", "consignee": "Divine"}, headers=h).json()["id"]
    _upload(client, h, sid, "shipping_line_proforma", CORDELIA.replace("CSX26JEDNSA021814", "CSXRCPT0001").splitlines())
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert float(s["line_amount_before_tax"]) == 135500.0      # proforma counts (every line: not Maersk) until a tax invoice
    _upload(client, h, sid, "shipping_line_invoice", ["Tax Invoice", "Bill of Lading CSXRCPT0001",
            "Total Base Amount INR 100,000.00", "I-GST Total taxes (see tax specification) INR 18,000.00",
            "Total Payable Amount INR 118,000.00"])
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert float(s["line_amount_before_tax"]) == 100000.0      # tax invoice replaces the proforma
    assert s["line_paid"] is False
    r = _upload(client, h, sid, "shipping_line_receipt", ["RECEIPT", "Amount Paid: INR 118,000.00"])
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["line_paid"] is True
    doc = r.get("document", r)
    assert float(doc["amount_total"]) == 118000.0


def test_line_paid_by_us_and_cfs_taxable_sections(client, admin_headers):
    from tests.test_invoice import _setup
    h = admin_headers
    sid = _setup(client, h, port_consignee="Divine")          # CFS paid by us, 40,000 + 7,200
    _upload(client, h, sid, "shipping_line_invoice", ["Tax Invoice", "Total Base Amount INR 10,000.00",
            "I-GST Total taxes (see tax specification) INR 1,800.00", "Total Payable Amount INR 11,800.00"])
    client.patch(f"/shipments/{sid}", json={"line_paid_by_us": True, "cfs_billed_as": "taxable"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    lines = {li["description"]: li for li in client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()["proforma"]["line_items"]}
    line, cfs = lines["Shipping Line (destination charges)"], lines["CFS Charges"]
    assert line["category"] == "reimbursement"
    assert cfs["category"] == "service" and cfs["gst_is_actual"] is False and float(cfs["gst_amount"]) == 7200.0


def test_draft_proforma_updates_automatically_one_shipping_line_total(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "274014260AUTO", "consignee": "Divine"}, headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    # invoice uploaded AFTER the proforma was started -> it appears on the draft by itself
    up = _upload(client, h, sid, "shipping_line_invoice", MAERSK.replace("274014260", "274014260AUTO").splitlines())
    doc_id = up.get("document", up)["id"]

    def line():
        p = next(x for x in client.get(f"/shipments/{sid}/proformas", headers=h).json() if x["id"] == pid)
        sl = [li for li in p["line_items"] if li["description"].startswith("Shipping Line")]
        assert len(sl) <= 1
        return sl[0] if sl else None

    sl = line()   # one total of the INR charges (USD freight left out), SAC "Liner Inv"
    assert (sl["sac_code"], sl["description"], sl["category"]) == ("Liner Inv", "Shipping Line (Maersk)", "cost_inclusion")
    assert (float(sl["amount"]), float(sl["gst_amount"])) == (1058050.0, 190449.0)

    # unticking a charge on the Overview updates the total on the draft
    client.patch(f"/shipments/{sid}/documents/{doc_id}/cost-inclusion", json={"excluded": [1, 2]}, headers=h)
    assert float(line()["amount"]) == 157500.0

    # a removed line isn't put back automatically; the button brings it back (as reimbursement now)
    client.delete(f"/proformas/{pid}/line-items/{line()['id']}", headers=h)
    client.patch(f"/shipments/{sid}", json={"line_paid_by_us": True}, headers=h)
    assert line() is None
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    assert line()["category"] == "reimbursement"

    # hand edit is kept through later changes
    client.patch(f"/proformas/{pid}/line-items/{line()['id']}", json={"rate": "150000"}, headers=h)
    client.patch(f"/shipments/{sid}/documents/{doc_id}/cost-inclusion", json={"reset": True}, headers=h)
    assert float(line()["amount"]) == 150000.0 and line()["is_manual"]


def test_exam_charge_follows_under_examination_and_payer_chain(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "EXAMAUTO0001", "consignee": "HKR - Mahrishi", "container": "3"},
                      headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"under_examination": True}, headers=h)
    p = next(x for x in client.get(f"/shipments/{sid}/proformas", headers=h).json() if x["id"] == pid)
    ec = [li for li in p["line_items"] if li["description"] == "Examination Charges"]
    assert len(ec) == 1 and ec[0]["category"] == "service" and float(ec[0]["amount"]) == 54000.0   # 18000 x 3
    client.patch(f"/shipments/{sid}", json={"under_examination": False}, headers=h)
    p = next(x for x in client.get(f"/shipments/{sid}/proformas", headers=h).json() if x["id"] == pid)
    assert not any(li["description"] == "Examination Charges" for li in p["line_items"])

    inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
    # buyer invoice: buyer (Bill To) pays Clarus
    assert inv["grand_total_label"] == f"{inv['bill_to']['name']} pays CLARUS LOGISTICS LLP"
    # seller invoice: seller pays buyer
    spid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "seller"}, headers=h).json()["id"]
    sinv = client.get(f"/proformas/{spid}/invoice", headers=h).json()
    assert sinv["grand_total_label"] == f"HKR pays {sinv['bill_to']['name']}"


def test_restore_removed_shipping_line(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "274014260RST", "consignee": "Divine"}, headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    _upload(client, h, sid, "shipping_line_invoice", MAERSK.replace("274014260", "274014260RST").splitlines())
    p = next(x for x in client.get(f"/shipments/{sid}/proformas", headers=h).json() if x["id"] == pid)
    sl = next(li for li in p["line_items"] if li["sac_code"] == "Liner Inv")
    p = client.delete(f"/proformas/{pid}/line-items/{sl['id']}", headers=h).json()
    assert p["suppressed"] == ["DO:Liner Inv"]
    p = client.post(f"/proformas/{pid}/restore", json={"key": "DO:Liner Inv"}, headers=h).json()
    assert p["suppressed"] is None and any(li["sac_code"] == "Liner Inv" for li in p["line_items"])
    # by charge code too; nothing to add -> 400
    assert client.post(f"/proformas/{pid}/restore", json={"key": "EC"}, headers=h).status_code == 400


def test_line_cost_inclusion_client_default_and_shipment_switch(client, admin_headers):
    """Client, 2026-09-29: for Harekrishna Rubber the shipping line invoice is not added to the
    cost inclusion — but a switch on the shipment can still add it (and can leave it out anywhere)."""
    h = admin_headers
    client.post("/organizations", json={"name": "Harekrishna Rubber Test Pvt Ltd", "short_names": "HKRT",
                                        "line_in_cost_inclusion": False}, headers=h)
    sid = client.post("/shipments", json={"mbl": "274014260HKR", "consignee": "HKRT - Mahrishi"}, headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    _upload(client, h, sid, "shipping_line_invoice", MAERSK.replace("274014260", "274014260HKR").splitlines())

    def line():
        p = next(x for x in client.get(f"/shipments/{sid}/proformas", headers=h).json() if x["id"] == pid)
        return next((li for li in p["line_items"] if li["description"].startswith("Shipping Line")), None)

    assert line() is None  # HKR (the HSS seller here): not in cost inclusion by default
    client.patch(f"/shipments/{sid}", json={"line_cost_inclusion": "include"}, headers=h)
    assert line() and line()["category"] == "cost_inclusion"  # switched on for this shipment
    client.patch(f"/shipments/{sid}", json={"line_cost_inclusion": None}, headers=h)
    assert line() is None  # back to auto
    # the switch can also leave it out on any other client's shipment
    other = client.post("/shipments", json={"mbl": "274014260OTH", "consignee": "Divine"}, headers=h).json()["id"]
    op = client.post(f"/shipments/{other}/proformas", headers=h).json()["id"]
    _upload(client, h, other, "shipping_line_invoice", MAERSK.replace("274014260", "274014260OTH").splitlines())
    has_line = lambda: any(li["description"].startswith("Shipping Line") for li in  # noqa: E731
                           next(x for x in client.get(f"/shipments/{other}/proformas", headers=h).json() if x["id"] == op)["line_items"])
    assert has_line()
    client.patch(f"/shipments/{other}", json={"line_cost_inclusion": "exclude"}, headers=h)
    assert not has_line()


def test_fta_number_after_the_mbl_is_split_off():
    """Client, 2026-09-29: 'LPL1543012-UKIN-160926-E96101' — the MBL is LPL1543012, the rest is the FTA no."""
    from app.tracker_import import split_fta

    assert split_fta("LPL1543012-UKIN-160926-E96101") == ("LPL1543012", "UKIN-160926-E96101")
    assert split_fta("HDMUBHMA79827900 -UKIN-100926-CEAACE") == ("HDMUBHMA79827900", "UKIN-100926-CEAACE")
    assert split_fta("BHMA07216400- UKIN-170926-342EE1") == ("BHMA07216400", "UKIN-170926-342EE1")
    assert split_fta("CSX26JEDNSA021814") == ("CSX26JEDNSA021814", None)
    assert split_fta("UKIN-160926-E96101") == ("UKIN-160926-E96101", None)  # nothing before it: leave alone

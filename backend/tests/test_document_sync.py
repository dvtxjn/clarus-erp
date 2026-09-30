from tests.conftest import be_pdf, cfs_pdf

def _processing_table(examined: bool):
    """'H. PROCESSING DETAILS' table as laid out on a real OOC copy."""
    rows = [
        ("Submission", "31-AUG-26", "17:43"),
        ("Assessment", "31-AUG-26", "17O:46"),  # watermark letter bleeding into the time, as on real copies
        ("Examination", "10-SEP-26", "16:27") if examined else ("Examination", "", ""),
        ("OOC", "10-09-2026", "16:40"),
        ("Finalisation", "", ""),
    ]
    out = [(300, 20, "OOC COPY"), (63, 486, "1.EVENT"), (130, 486, "2.DATE"), (186, 486, "3.TIME")]
    for i, (event, d, t) in enumerate(rows):
        top = 500 + i * 9
        out += [(63, top, event), (124, top, d), (186, top, t)]
    return tuple(x for x in out if x[2])


OOC_LINES = _processing_table(examined=True)


def _new_shipment(client, h, **kw):
    return client.post("/shipments", json={"mbl": "MEDU1234567890", **kw}, headers=h).json()["id"]


def _upload(client, h, sid, doc_type, pdf):
    r = client.post(f"/shipments/{sid}/documents", data={"document_type": doc_type},
                    files={"file": ("x.pdf", pdf, "application/pdf")}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_ooc_upload_fills_shipment(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "ooc_bill_of_entry", be_pdf(be_no="5550001", extra=OOC_LINES))
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert (s["be_no"], s["be_dt"], s["port"]) == ("5550001", "2026-03-05", "INNSA1")
    assert s["ooc"] and s["duty_paid"] and s["status"] == "ooc_done"
    assert s["ooc_date"] == "2026-09-10"
    assert s["under_examination"] is True and s["examination_at"] == "10-SEP-26 16:27"
    assert float(s["duty_amount"]) == 61500.0 and float(s["assessable_value"]) == 250000.0
    assert "BE No" in doc["extraction"]["updated"] and "Duty Paid" in doc["extraction"]["updated"]


def test_ooc_without_exam_date_means_not_examined(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    _upload(client, admin_headers, sid, "ooc_bill_of_entry", be_pdf(be_no="5550002", extra=_processing_table(examined=False)))
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["under_examination"] is False


def test_be_mismatch_is_reported_not_overwritten(client, admin_headers):
    sid = _new_shipment(client, admin_headers, be_no="1111111")
    doc = _upload(client, admin_headers, sid, "assessed_bill_of_entry", be_pdf(be_no="5550003"))
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert s["be_no"] == "1111111" and s["status"] == "be_assessed"
    assert any("BE No" in n for n in doc["extraction"]["notes"])


def test_cfs_invoice_amounts(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert s["cfs_inv_received"] is True
    assert (float(s["cfs_amount_before_tax"]), float(s["cfs_gst_amount"]), float(s["cfs_amount_total"])) == (
        108560.0, 19540.8, 128100.8)


def test_mbl_with_hbl_in_same_cell_is_not_a_mismatch(client, admin_headers):
    sid = client.post("/shipments", json={"mbl": "MEDU1234567890/HBL998877", "gross_wt": "24.5 MTS"},
                      headers=admin_headers).json()["id"]
    doc = _upload(client, admin_headers, sid, "ooc_bill_of_entry", be_pdf(be_no="5550009", extra=OOC_LINES))
    assert doc["extraction"]["notes"] == []
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert s["hbl"] is None and s["gross_wt"] == "24.501 MTS"  # BE's weight (kg) always wins


def test_cfs_paid_by_us_makes_tax_invoice_expected(client, admin_headers):
    sid = client.post("/shipments", json={"mbl": "CFSFLAG1", "hs_code_id": 1}, headers=admin_headers).json()["id"]
    row = lambda: next(r for r in client.get(f"/shipments/{sid}/documents/checklist", headers=admin_headers).json()
                       if r["document_type"] == "cfs_tax_invoice")  # noqa: E731
    assert row()["optional"] is True
    r = client.patch(f"/shipments/{sid}", json={"cfs_paid_by_us": True, "tds_deducted": True, "tds_on_cfs": True},
                     headers=admin_headers).json()
    assert (r["cfs_paid_by_us"], r["tds_deducted"], r["tds_on_cfs"]) == (True, True, True)
    assert row()["optional"] is False


def test_add_document_from_google_drive(client, admin_headers, monkeypatch):
    from app.integrations import google_drive

    calls = {}

    async def fake_fetch(file_id, token):
        calls["args"] = (file_id, token)
        return google_drive.DriveFile(file_id=file_id, name="OOC copy.pdf",
                                      web_link="https://drive.google.com/file/d/abc/view",
                                      content=be_pdf(be_no="5550020", extra=OOC_LINES).getvalue())

    monkeypatch.setattr(google_drive, "fetch_drive_pdf", fake_fetch)
    sid = _new_shipment(client, admin_headers)
    r = client.post(f"/shipments/{sid}/documents/from-drive", headers=admin_headers,
                    json={"document_type": "ooc_bill_of_entry", "file_id": "1AbCdEfGhIjK", "access_token": "tok"})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert calls["args"] == ("1AbCdEfGhIjK", "tok")
    assert doc["drive_link"] == "https://drive.google.com/file/d/abc/view"
    assert doc["original_filename"] == "OOC copy.pdf" and "OOC" in doc["extraction"]["updated"]
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["be_no"] == "5550020"


def test_drive_errors_are_readable(client, admin_headers, monkeypatch):
    from app.integrations import google_drive

    async def not_pdf(file_id, token):
        raise google_drive.DriveError("'scan.jpg' isn't a PDF — pick the PDF copy of the document.")

    monkeypatch.setattr(google_drive, "fetch_drive_pdf", not_pdf)
    sid = _new_shipment(client, admin_headers)
    r = client.post(f"/shipments/{sid}/documents/from-drive", headers=admin_headers,
                    json={"document_type": "bl_copy", "file_id": "1AbCdEfGhIjK", "access_token": "tok"})
    assert r.status_code == 400 and "isn't a PDF" in r.json()["detail"]


def test_gross_weight_from_be_is_always_taken_in_mts(client, admin_headers):
    sid = client.post("/shipments", json={"mbl": "MEDU1234567890", "gross_wt": "84.000 MTS"}, headers=admin_headers).json()["id"]
    doc = _upload(client, admin_headers, sid, "assessed_bill_of_entry", be_pdf(be_no="5550030", gw="24500.5"))
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["gross_wt"] == "24.501 MTS"
    assert "Gross Wt" in doc["extraction"]["updated"] and doc["extraction"]["notes"] == []


def test_cfs_payment_after_tds(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())  # basic 108560, GST 19540.80
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert s["cfs_payment_after_tds"] is None  # not paid by us -> invoice only
    s = client.patch(f"/shipments/{sid}", json={"cfs_paid_by_us": True}, headers=admin_headers).json()
    assert s["tds_on_cfs"] is True
    assert float(s["cfs_tds_amount"]) == 2171.20  # 2% of 108560
    assert float(s["cfs_payment_after_tds"]) == 125929.60  # 108560 + 19540.80 - 2171.20
    s = client.patch(f"/shipments/{sid}", json={"tds_on_cfs": False}, headers=admin_headers).json()
    assert s["cfs_tds_amount"] is None and float(s["cfs_payment_after_tds"]) == 128100.80


def test_cfs_tds_rate_needs_the_admin_switch(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())  # basic 108560
    client.patch(f"/shipments/{sid}", json={"cfs_paid_by_us": True}, headers=admin_headers)
    assert client.get("/settings/public", headers=admin_headers).json() == {"tds_rate_editable": False}
    r = client.patch(f"/shipments/{sid}", json={"cfs_tds_rate": 10}, headers=admin_headers)
    assert r.status_code == 422 and "fixed at 2%" in r.json()["detail"]
    assert client.patch(f"/shipments/{sid}", json={"cfs_tds_rate": 2}, headers=admin_headers).status_code == 200

    assert client.put("/settings/tds_rate_editable", json={"value": True}, headers=admin_headers).status_code == 200
    s = client.patch(f"/shipments/{sid}", json={"cfs_tds_rate": 10}, headers=admin_headers).json()
    assert float(s["cfs_tds_rate"]) == 10 and float(s["cfs_tds_amount"]) == 10856.00
    s = client.patch(f"/shipments/{sid}", json={"cfs_tds_rate": 1}, headers=admin_headers).json()
    assert float(s["cfs_tds_amount"]) == 1085.60
    assert client.patch(f"/shipments/{sid}", json={"cfs_tds_rate": 25}, headers=admin_headers).status_code == 422
    s = client.patch(f"/shipments/{sid}", json={"cfs_tds_rate": 2}, headers=admin_headers).json()
    assert s["cfs_tds_rate"] is None and float(s["cfs_tds_amount"]) == 2171.20  # 2% is stored as empty


def test_upload_is_also_saved_into_linked_drive_folder(client, admin_headers, monkeypatch):
    from app.integrations import google_drive
    saved = {}

    async def fake_upload(folder_id, name, content, token):
        saved.update(folder=folder_id, name=name, token=token, pdf=content[:4])
        return "drivefile123", "https://drive.google.com/file/d/drivefile123/view"

    monkeypatch.setattr(google_drive, "upload_pdf", fake_upload)
    sid = _new_shipment(client, admin_headers)
    client.patch(f"/shipments/{sid}", json={"drive_folder_id": "1FolderIdAbc",
                                            "drive_folder_link": "https://drive.google.com/drive/folders/1FolderIdAbc"},
                 headers=admin_headers)
    r = client.post(f"/shipments/{sid}/documents", data={"document_type": "bl_copy", "drive_access_token": "tok"},
                    files={"file": ("bl.pdf", cfs_pdf(), "application/pdf")}, headers=admin_headers)
    doc = r.json()
    assert saved["folder"] == "1FolderIdAbc" and saved["token"] == "tok" and saved["pdf"] == b"%PDF"
    assert saved["name"] == doc["generated_filename"]
    assert doc["drive_link"].endswith("/view")
    # without a token: upload still works, with a note
    r = client.post(f"/shipments/{sid}/documents", data={"document_type": "packing_list"},
                    files={"file": ("pl.pdf", cfs_pdf(), "application/pdf")}, headers=admin_headers)
    assert r.status_code == 201 and any("Drive" in n for n in r.json()["extraction"]["notes"])


def test_reread_document(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())
    client.patch(f"/shipments/{sid}", json={}, headers=admin_headers)
    r = client.post(f"/shipments/{sid}/documents/{doc['id']}/reread", headers=admin_headers)
    assert r.status_code == 200 and r.json()["extraction"]["fields"]["cfs_after_tax"] == 128100.8


def test_remove_document_moves_file_aside(client, admin_headers):
    import os
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "cfs_proforma_invoice", cfs_pdf())
    assert client.delete(f"/shipments/{sid}/documents/{doc['id']}", headers=admin_headers).status_code == 204
    assert all(d["id"] != doc["id"] for d in client.get(f"/shipments/{sid}/documents", headers=admin_headers).json())
    assert not os.path.exists(doc["file_path"])
    removed = os.path.join(os.environ["DOCUMENT_STORAGE_ROOT"], "_removed", str(sid))
    assert os.listdir(removed) == [f"{doc['id']} - {os.path.basename(doc['file_path'])}"]


def _cfs_totals(client, h, sid):
    s = client.get(f"/shipments/{sid}", headers=h).json()
    return tuple(None if s[k] is None else float(s[k])
                 for k in ("cfs_amount_before_tax", "cfs_gst_amount", "cfs_amount_total"))


def test_multiple_cfs_invoices_are_summed_tax_over_proforma(client, admin_headers):
    h = admin_headers
    sid = _new_shipment(client, h)
    _upload(client, h, sid, "cfs_proforma_invoice", cfs_pdf(before="1,000.00", gst="180.00", after="1,180.00"))
    _upload(client, h, sid, "cfs_proforma_invoice", cfs_pdf(before="500.00", gst="90.00", after="590.00"))
    assert _cfs_totals(client, h, sid) == (1500.0, 270.0, 1770.0)  # proformas summed
    t1 = _upload(client, h, sid, "cfs_tax_invoice", cfs_pdf(before="1,000.00", gst="180.00", after="1,180.00"))
    assert _cfs_totals(client, h, sid) == (1000.0, 180.0, 1180.0)  # tax invoices replace proformas
    t2 = _upload(client, h, sid, "cfs_tax_invoice", cfs_pdf(before="600.00", gst="108.00", after="708.00"))
    assert _cfs_totals(client, h, sid) == (1600.0, 288.0, 1888.0)
    rows = client.get(f"/shipments/{sid}/documents/checklist", headers=h).json()
    tax_row = next(r for r in rows if r["document_type"] == "cfs_tax_invoice")
    assert [d["id"] for d in tax_row["documents"]] == [t1["id"], t2["id"]]
    client.delete(f"/shipments/{sid}/documents/{t2['id']}", headers=h)
    assert _cfs_totals(client, h, sid) == (1000.0, 180.0, 1180.0)


def test_correcting_a_misread_invoice(client, admin_headers):
    h = admin_headers
    sid = _new_shipment(client, h)
    doc = _upload(client, h, sid, "cfs_tax_invoice", cfs_pdf())  # 108560 + 19540.80
    r = client.patch(f"/shipments/{sid}/documents/{doc['id']}/amounts", headers=h,
                     json={"amount_before_tax": "100000.00", "gst_amount": "18000.00"})
    assert r.status_code == 200 and float(r.json()["amount_total"]) == 118000.0 and r.json()["amounts_edited"]
    assert _cfs_totals(client, h, sid) == (100000.0, 18000.0, 118000.0)
    client.post(f"/shipments/{sid}/documents/{doc['id']}/reread", headers=h)  # hand fix survives a re-read
    assert _cfs_totals(client, h, sid) == (100000.0, 18000.0, 118000.0)
    s = client.patch(f"/shipments/{sid}", json={"cfs_paid_by_us": True, "duty_amount": "61000.50"}, headers=h).json()
    assert float(s["cfs_payment_after_tds"]) == 116000.0  # 100000 + 18000 - 2% of 100000
    assert float(s["duty_amount"]) == 61000.5


def test_agency_and_exam_are_per_container(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "PERCNTR1", "container": "5"}, headers=h).json()["id"]
    charges = {c["code"]: c for c in client.get("/charge-master", headers=h).json()}
    assert charges["AC"]["calculation_basis"] == "per_container" and charges["EC"]["calculation_basis"] == "per_container"
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    p = client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges["AC"]["id"], "rate": "1500"},
                    headers=h).json()
    li = next(x for x in p["line_items"] if float(x["rate"]) == 1500)  # (Agency at 7,000 is pre-filled too)
    assert float(li["quantity"]) == 5 and float(li["amount"]) == 7500 and float(li["gst_amount"]) == 1350
    assert float(li["total"]) == 8850  # (1500 x 5 containers) + 18% GST
    p = client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges["DC"]["id"], "rate": "500"},
                    headers=h).json()
    assert float(next(x for x in p["line_items"] if float(x["rate"]) == 500)["quantity"]) == 1  # flat charge
    sid2 = client.post("/shipments", json={"mbl": "PERCNTR2"}, headers=h).json()["id"]
    pid2 = client.post(f"/shipments/{sid2}/proformas", headers=h).json()["id"]
    r = client.post(f"/proformas/{pid2}/line-items", json={"charge_master_id": charges["EC"]["id"], "rate": "1000"},
                    headers=h)
    assert r.status_code == 400 and "per container" in r.json()["detail"]


def test_assessed_upload_that_is_really_an_ooc_copy_is_refiled(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "assessed_bill_of_entry", be_pdf(be_no="5550040", extra=OOC_LINES))
    assert doc["document_type"] == "ooc_bill_of_entry" and doc["generated_filename"].startswith("OOC - ")
    assert doc["extraction"]["notes"][0].startswith("This is an OOC copy")
    s = client.get(f"/shipments/{sid}", headers=admin_headers).json()
    assert s["ooc"] is True and s["status"] == "ooc_done"


def test_file_tagged_ooc_without_ooc_marking_does_not_tick_ooc(client, admin_headers):
    sid = _new_shipment(client, admin_headers)
    doc = _upload(client, admin_headers, sid, "ooc_bill_of_entry", be_pdf(be_no="5550041"))
    assert any("doesn't look like an OOC copy" in n for n in doc["extraction"]["notes"])
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["ooc"] is False


def test_delete_draft_proforma_only(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "PFDEL1"}, headers=h).json()["id"]
    p1 = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    p2 = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    client.patch(f"/proformas/{p1}", json={"status": "sent"}, headers=h)
    assert client.delete(f"/proformas/{p1}", headers=h).status_code == 400  # sent: kept
    assert client.delete(f"/proformas/{p2}", headers=h).status_code == 204
    assert [p["id"] for p in client.get(f"/shipments/{sid}/proformas", headers=h).json()] == [p1]


def test_shipping_line_invoices_summed_and_editable(client, admin_headers):
    from tests.conftest import make_pdf
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "SLINV1", "hs_code_id": 1}, headers=h).json()["id"]
    rows = client.get(f"/shipments/{sid}/documents/checklist", headers=h).json()
    row = next(r for r in rows if r["document_type"] == "shipping_line_invoice")
    assert row["required"] and not row["optional"]
    inv = make_pdf([(40, 40, "DESTINATION CHARGES INVOICE"), (40, 60, "Total Taxable Value : 12,000.00"),
                    (40, 72, "Total GST : 2,160.00"), (40, 84, "Grand Total : 14,160.00")])
    d1 = _upload(client, h, sid, "shipping_line_invoice", inv)
    assert float(d1["amount_total"]) == 14160.0 and d1["generated_filename"].startswith("SL-DSC - ")
    unreadable = _upload(client, h, sid, "shipping_line_invoice", make_pdf([(40, 40, "scan")]))
    assert any("Enter the amounts by hand" in n for n in unreadable["extraction"]["notes"])
    client.patch(f"/shipments/{sid}/documents/{unreadable['id']}/amounts", headers=h,
                 json={"amount_before_tax": "1000", "gst_amount": "180"})
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert (float(s["line_amount_before_tax"]), float(s["line_gst_amount"]), float(s["line_amount_total"])) == (
        13000.0, 2340.0, 15340.0)
    assert s["cfs_amount_total"] is None  # separate from CFS


def test_same_invoice_added_twice_counts_once(client, admin_headers):
    """Client, 2026-09-29: a tax invoice uploaded twice (e.g. upload + pick from Drive) was
    summed twice. The invoice number (or IRN) identifies it: counted once, marked duplicate."""
    from tests.conftest import make_pdf
    h = admin_headers
    sid = _new_shipment(client, h)

    def inv(number, total):
        return make_pdf([(40, 40, "NAVKAR CFS - IMPORT TAX INVOICE"), (40, 52, f"Invoice No  : {number} Invoice Date : 10/Sep/2026"),
                         (40, 60, "BOE No: 2345678"), (40, 72, "BL No: MEDU1234567890"),
                         (40, 120, "Total Amount Before Tax: 40,000.00"), (40, 132, "Tax Amount: GST: 7,200.00"),
                         (40, 144, f"Total Amount After Tax: {total}")])
    a = _upload(client, h, sid, "cfs_tax_invoice", inv("PI/DPDI/07609/27", "47,200.00"))
    b = _upload(client, h, sid, "cfs_tax_invoice", inv("PI/DPDI/07609/27", "47,200.00"))
    assert a["extraction"]["fields"]["invoice_no"] == "PI/DPDI/07609/27"
    assert _cfs_totals(client, h, sid) == (40000.0, 7200.0, 47200.0)  # not 94,400
    docs = {d["id"]: d for d in client.get(f"/shipments/{sid}/documents", headers=h).json()}
    assert docs[b["id"]]["extraction"]["duplicate_of"] == a["id"] and not docs[a["id"]]["extraction"]["duplicate_of"]
    _upload(client, h, sid, "cfs_tax_invoice", inv("PI/DPDI/07610/27", "47,200.00"))  # a different invoice adds up
    assert _cfs_totals(client, h, sid) == (80000.0, 14400.0, 94400.0)
    client.delete(f"/shipments/{sid}/documents/{a['id']}", headers=h)  # first copy removed: the other one counts
    assert _cfs_totals(client, h, sid) == (80000.0, 14400.0, 94400.0)


def test_invoice_without_gst_is_flagged(client, admin_headers):
    """Client, 2026-09-29: CFS / shipping line invoices (and BE duty) always have GST — flag it when missing."""
    h = admin_headers
    sid = _new_shipment(client, h)
    doc = _upload(client, h, sid, "cfs_tax_invoice", cfs_pdf(before="1,000.00", gst="0.00", after="1,000.00"))
    assert doc["extraction"]["fields"].get("gst_missing") is True
    assert any("GST not found" in n for n in doc["extraction"]["notes"])
    ok = _upload(client, h, sid, "cfs_tax_invoice", cfs_pdf())
    assert not ok["extraction"]["fields"].get("gst_missing")

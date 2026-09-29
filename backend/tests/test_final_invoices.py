"""Final invoices from a proforma — modelled on the client's CL/200/26-27 (tax) and
RI/CL/200/26-27 (reimbursement) for BAHUBALI RUBBER (Rajasthan -> IGST)."""
from tests.test_invoice import _setup


def test_final_invoices_from_proforma(client, admin_headers):
    h = admin_headers
    client.post("/organizations", json={"name": "BAHUBALI RUBBER PRIVATE LIMITED", "gstin": "08AACCB2783N1ZA",
                                        "pan": "AACCB2783N", "address": "E 700, RIICO INDUSTRIAL AREA CHOPANKI, Bhiwadi - 301019"},
                headers=h)
    sid = client.post("/shipments", json={"mbl": "274483845/QDDR2607499", "job": "165", "consignee": "BAHUBALI RUBBER",
                                          "container": "1"}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"duty_amount": "1436691", "igst_amount": "0", "port": "INGHR6"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    charges = {c["code"]: c["id"] for c in client.get("/charge-master", headers=h).json()}
    client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges["OTHERCHARGES"], "rate": 9500, "quantity": 1}, headers=h)

    r = client.post(f"/proformas/{pid}/final-invoices", headers=h)
    assert r.status_code == 201
    inv = {i["kind"]: i for i in r.json()}
    tax, reim = inv["tax"], inv["reimbursement"]
    # tax invoice: only Billed by Clarus — Agency 7,000 x 1 + Other 9,500; IGST (Rajasthan)
    assert [l["description"] for l in tax["lines"]] == ["Agency Charges", "Other Charges"]
    assert tax["intra_state"] is False and tax["place_of_supply"] == "[8] Rajasthan"
    assert tax["totals"]["before_tax"] == "16500.00" and tax["totals"]["gst"] == "2970.00"
    assert tax["totals"]["net_payable"] == "19470.00"
    assert tax["totals"]["in_words"] == "Nineteen Thousand Four Hundred Seventy Only."
    assert tax["header"]["job_number"].startswith("IMP/0165/") and tax["header"]["mbl_no"] == "274483845"
    assert tax["header"]["hbl_no"] == "QDDR2607499"
    assert [k for k, _ in tax["header_fields"]] == ["be_no", "be_date", "mbl_no", "hbl_no", "no_of_containers", "origin_port"]
    # reimbursement: customs duty as pure agent, no GST
    assert [(l["description"], l["tax_type"]) for l in reim["lines"]][0] == ("Customs Duty", "P")
    assert reim["totals"]["gst"] == "0.00" and reim["totals"]["net_payable"] == "1436691.00"
    assert reim["totals"]["in_words"] == "Fourteen Lakh Thirty Six Thousand Six Hundred Ninety One Only."

    # manual override, then issue: the pair shares the number
    t = client.patch(f"/final-invoices/{tax['id']}", json={"header": {"origin_port": "Qingdao"},
                     "lines": [*tax["lines"][:1], {**tax["lines"][1], "sub_description": "Transportation"}]}, headers=h).json()
    assert t["header"]["origin_port"] == "Qingdao" and t["lines"][1]["sub_description"] == "Transportation"
    t = client.post(f"/final-invoices/{tax['id']}/issue", headers=h).json()
    r2 = client.post(f"/final-invoices/{reim['id']}/issue", headers=h).json()
    n = t["number"].split("/")[1]
    assert t["number"].startswith("CL/") and r2["number"] == f"RI/CL/{n}/{t['number'].split('/')[2]}"
    # issued: still alterable until the 10th of next month (client, 2026-09-30); IRN any time
    if __import__("os").environ.get("TEST_DATABASE_URL"):  # altering needs Postgres (the lock trigger's switch)
        assert client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "x"}, headers=h).status_code == 200
    assert client.patch(f"/final-invoices/{tax['id']}", json={"irn": "abc123"}, headers=h).json()["irn"] == "abc123"
    pdf = client.get(f"/final-invoices/{tax['id']}.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # can't re-create from a proforma with issued invoices
    assert client.post(f"/proformas/{pid}/final-invoices", headers=h).status_code == 400


def test_intra_state_splits_cgst_sgst(client, admin_headers):
    h = admin_headers
    client.post("/organizations", json={"name": "Maha Intra Traders", "gstin": "27AAAAA0000A1Z5"}, headers=h)
    sid = client.post("/shipments", json={"mbl": "INTRA0001", "consignee": "Maha Intra Traders", "container": "2"},
                      headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    tax = next(i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json() if i["kind"] == "tax")
    ln = tax["lines"][0]
    assert tax["intra_state"] and ln["cgst"] == ln["sgst"] == "1260.00" and ln["igst"] is None


def test_no_reimbursement_still_issued_as_not_applicable_and_pair_issued_together(client, admin_headers):
    """Client, 2026-09-30: tax and reimbursement always share one number. With no charges paid
    by us, the reimbursement invoice is still issued — no charge heads, "BILL CANCELLED — NOT
    APPLICABLE" — and both are issued in one action; one PDF with both, or two."""
    import pypdfium2

    h = admin_headers
    client.post("/organizations", json={"name": "Solo Tax Traders", "gstin": "24AAAAA1111A1Z5"}, headers=h)
    sid = client.post("/shipments", json={"mbl": "SOLOTAX0001", "consignee": "Solo Tax Traders", "container": "1"},
                      headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]  # agency only: nothing reimbursed
    made = {i["kind"]: i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json()}
    assert set(made) == {"tax", "reimbursement"}
    assert made["reimbursement"]["not_applicable"] is True and made["reimbursement"]["lines"] == []
    assert made["tax"]["not_applicable"] is False

    both = client.post(f"/proformas/{pid}/final-invoices/issue", headers=h).json()
    nums = {i["kind"]: i["number"] for i in both}
    n, fy = nums["tax"].split("/")[1], nums["tax"].split("/")[2]
    assert nums["reimbursement"] == f"RI/CL/{n}/{fy}"                    # the chain doesn't break
    assert all(i["status"] == "issued" for i in both)
    assert client.post(f"/proformas/{pid}/final-invoices/issue", headers=h).status_code == 400  # already issued

    pdf = client.get(f"/proformas/{pid}/final-invoices.pdf", headers=h)
    assert pdf.status_code == 200 and len(pypdfium2.PdfDocument(pdf.content)) == 2   # tax + reimbursement
    ri = next(i for i in both if i["kind"] == "reimbursement")
    text = pypdfium2.PdfDocument(client.get(f"/final-invoices/{ri['id']}.pdf", headers=h).content)[0].get_textpage().get_text_range()
    assert "BILL CANCELLED" in text and "NOT APPLICABLE" in text


import os

import pytest


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="altering issued invoices needs Postgres")
def test_altering_an_issued_invoice(client, admin_headers, monkeypatch):
    """Client, 2026-09-30: issued bills can be altered (mistakes happen) until the 10th of the next
    month; if e-invoicing applies (admin setting), only after confirming the e-invoice isn't filed."""
    from datetime import date as real_date

    import app.routers.final_invoices as fi
    from app.invoice.final import alter_until
    from app.models.final_invoice import FinalInvoice

    assert alter_until(FinalInvoice(invoice_date=real_date(2026, 9, 17))) == real_date(2026, 10, 10)
    assert alter_until(FinalInvoice(invoice_date=real_date(2026, 12, 3))) == real_date(2027, 1, 10)

    h = admin_headers
    client.post("/organizations", json={"name": "Alter Traders", "gstin": "24AAAAA2222A1Z5"}, headers=h)
    sid = client.post("/shipments", json={"mbl": "ALTER0001", "consignee": "Alter Traders", "container": "1"},
                      headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    client.post(f"/proformas/{pid}/final-invoices", headers=h)
    tax = next(i for i in client.post(f"/proformas/{pid}/final-invoices/issue", headers=h).json() if i["kind"] == "tax")
    assert tax["alter_until"]

    # e-invoicing off (default): alter straight away, number kept
    r = client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "corrected"}, headers=h)
    assert r.status_code == 200 and r.json()["remarks"] == "corrected" and r.json()["number"] == tax["number"]

    # e-invoicing on: asked first; filed = blocked; not filed = altered
    assert client.put("/settings/e_invoicing", json={"value": True}, headers=h).json()["e_invoicing"] is True
    ask = client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "again"}, headers=h)
    assert ask.status_code == 409 and ask.json()["detail"]["ask"] == "e_invoice_filed"
    assert client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "again", "e_invoice_filed": True},
                        headers=h).status_code == 400
    ok = client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "again", "e_invoice_filed": False}, headers=h)
    assert ok.status_code == 200 and ok.json()["remarks"] == "again"
    # an IRN entered = filed
    client.patch(f"/final-invoices/{tax['id']}", json={"irn": "IRN123"}, headers=h)
    assert client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "x", "e_invoice_filed": False},
                        headers=h).status_code == 400
    client.put("/settings/e_invoicing", json={"value": False}, headers=h)

    # after the 10th of next month: no longer
    class Later(real_date):
        @classmethod
        def today(cls):
            return real_date(2099, 1, 1)

    monkeypatch.setattr(fi, "date", Later)
    late = client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "late"}, headers=h)
    assert late.status_code == 400 and "credit note" in late.json()["detail"]


def test_settings_are_admin_only(client, admin_headers):
    assert client.put("/settings/e_invoicing", json={"value": "yes"}, headers=admin_headers).status_code == 422
    assert client.put("/settings/nope", json={"value": True}, headers=admin_headers).status_code == 404
    assert client.get("/settings").status_code == 401

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
    # issued = locked (IRN still allowed)
    assert client.patch(f"/final-invoices/{tax['id']}", json={"remarks": "x"}, headers=h).status_code == 400
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

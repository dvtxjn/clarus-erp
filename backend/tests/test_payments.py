"""P1 payments & outstanding (client, 2026-09-30): money received is set against issued invoices
(amount + TDS the client deducted); outstanding and ageing per client; a statement PDF; a payment
entered by mistake is soft-deleted by the admin and can be restored."""
import pypdfium2


def _issued_pair(client, h, name, gstin, mbl):
    client.post("/organizations", json={"name": name, "gstin": gstin}, headers=h)
    sid = client.post("/shipments", json={"mbl": mbl, "consignee": name, "container": "1"}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"duty_amount": "100000", "igst_amount": "0"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    client.post(f"/proformas/{pid}/final-invoices", headers=h)
    return {i["kind"]: i for i in client.post(f"/proformas/{pid}/final-invoices/issue", headers=h).json()}


def test_payment_split_tds_outstanding_and_statement(client, admin_headers):
    h = admin_headers
    pair = _issued_pair(client, h, "Payer Traders", "24AAAAA5555A1Z5", "PAY0001")
    tax, reim = pair["tax"], pair["reimbursement"]
    tax_net, reim_net = float(tax["totals"]["net_payable"]), float(reim["totals"]["net_payable"])

    rec = client.get("/receivables", params={"client": "payer traders"}, headers=h).json()["clients"][0]
    assert float(rec["outstanding"]) == tax_net + reim_net and len(rec["invoices"]) == 2
    assert float(rec["buckets"]["0-30"]) == tax_net + reim_net

    # too much against one invoice: refused
    bad = client.post("/payments", json={"received_on": "2026-09-30", "party": "Payer Traders", "amount": str(tax_net + 5000),
                                         "allocations": [{"invoice_id": tax["id"], "amount": str(tax_net + 5000)}]}, headers=h)
    assert bad.status_code == 400
    # reimbursement in full; tax invoice with 2% TDS deducted by the client; ₹1,000 extra stays on account
    tds = round(float(tax["totals"]["sub_taxable"]) * 0.02, 2)
    paid = round(tax_net - tds, 2)
    r = client.post("/payments", json={
        "received_on": "2026-09-30", "party": "Payer Traders", "party_gstin": "24AAAAA5555A1Z5",
        "amount": str(round(paid + reim_net + 1000, 2)), "mode": "NEFT", "reference": "UTR123",
        "allocations": [{"invoice_id": tax["id"], "amount": str(paid), "tds": str(tds)},
                        {"invoice_id": reim["id"], "amount": str(reim_net)}]}, headers=h)
    assert r.status_code == 201 and float(r.json()["unallocated"]) == 1000.0
    assert client.get("/receivables", params={"client": "payer traders"}, headers=h).json()["clients"] == []
    everything = client.get("/receivables", params={"client": "payer traders", "include_paid": True}, headers=h).json()["clients"][0]
    assert {i["pay_status"] for i in everything["invoices"]} == {"paid"} and float(everything["on_account"]) == 1000.0

    # entered by mistake: the admin deletes it -> outstanding again; Recently deleted can restore it
    assert client.delete(f"/payments/{r.json()['id']}", headers=h).status_code == 204
    again = client.get("/receivables", params={"client": "payer traders"}, headers=h).json()["clients"][0]
    assert float(again["outstanding"]) == tax_net + reim_net
    assert any(d["kind"] == "payment" for d in client.get("/deleted", headers=h).json())
    assert client.post(f"/deleted/payment/{r.json()['id']}/restore", headers=h).status_code == 200
    assert client.get("/receivables", params={"client": "payer traders"}, headers=h).json()["clients"] == []

    # statement of account for a client with something outstanding
    other = _issued_pair(client, h, "Statement Traders", "24AAAAA6666A1Z5", "PAY0002")
    pdf = client.get("/receivables/statement.pdf", params={"client": "Statement Traders"}, headers=h)
    assert pdf.status_code == 200 and "STATEMENT OF ACCOUNT" in pypdfium2.PdfDocument(pdf.content)[0].get_textpage().get_text_range()
    assert other["tax"]["number"]


def test_on_account_allocated_later_tds_on_tax_only_and_exact_statement(client, admin_headers):
    h = admin_headers
    pair = _issued_pair(client, h, "Advance Traders", "24AAAAA7777A1Z5", "PAY0003")
    tax, reim = pair["tax"], pair["reimbursement"]
    # a second client whose name contains the first one's: the statement must not mix them up
    _issued_pair(client, h, "Advance Traders Exports", "24AAAAA8888A1Z5", "PAY0004")
    sid = tax["shipment_id"]
    client.patch(f"/shipments/{sid}", json={"tds_deducted": True}, headers=h)

    c = client.get("/receivables", params={"client": "advance traders"}, headers=h).json()["clients"]
    c = next(x for x in c if x["gstin"] == "24AAAAA7777A1Z5")
    by_kind = {i["kind"]: i for i in c["invoices"]}
    # TDS is cut on the service (tax) invoice only — never on the reimbursement
    assert by_kind["tax"]["tds_expected"] and not by_kind["reimbursement"]["tds_expected"]
    est = round(float(tax["totals"]["sub_taxable"]) * 0.02, 2)
    assert float(by_kind["tax"]["tds_estimate"]) == est and float(by_kind["reimbursement"]["tds_estimate"]) == 0
    assert c["key"] == "gstin:24AAAAA7777A1Z5"

    # an advance, not set against anything: it's on account and the net due drops by it
    adv = client.post("/payments", json={"received_on": "2026-09-30", "party": "Advance Traders",
                                         "party_gstin": "24AAAAA7777A1Z5", "amount": "5000"}, headers=h).json()
    c = next(x for x in client.get("/receivables", params={"client": "advance traders"}, headers=h).json()["clients"]
             if x["key"] == "gstin:24AAAAA7777A1Z5")
    total = float(tax["totals"]["net_payable"]) + float(reim["totals"]["net_payable"])
    assert float(c["on_account"]) == 5000 and float(c["net_due"]) == round(total - 5000 - est, 2)

    # later: set it against the reimbursement invoice
    r = client.post(f"/payments/{adv['id']}/allocate", json={"allocations": [{"invoice_id": reim["id"], "amount": "3000"}]},
                    headers=h)
    assert r.status_code == 200 and float(r.json()["unallocated"]) == 2000
    assert r.json()["allocations"][0]["mbl"] == "PAY0003"
    # more than is left on account: refused
    assert client.post(f"/payments/{adv['id']}/allocate", json={"allocations": [{"invoice_id": reim["id"], "amount": "2500"}]},
                       headers=h).status_code == 400
    # another client's invoice: refused
    other = next(x for x in client.get("/receivables", params={"client": "advance traders exports"}, headers=h)
                 .json()["clients"])
    assert client.post(f"/payments/{adv['id']}/allocate",
                       json={"allocations": [{"invoice_id": other["invoices"][0]["id"], "amount": "100"}]},
                       headers=h).status_code == 400
    # the rest, again against the same invoice: merged into one line
    r = client.post(f"/payments/{adv['id']}/allocate", json={"allocations": [{"invoice_id": reim["id"], "amount": "2000"}]},
                    headers=h).json()
    assert len(r["allocations"]) == 1 and float(r["allocations"][0]["amount"]) == 5000 and float(r["unallocated"]) == 0
    c = next(x for x in client.get("/receivables", params={"client": "advance traders"}, headers=h).json()["clients"]
             if x["key"] == "gstin:24AAAAA7777A1Z5")
    assert float(c["outstanding"]) == round(total - 5000, 2) and float(c["on_account"]) == 0

    # statement by key: exactly that client, with its payments
    pdf = client.get("/receivables/statement.pdf", params={"client": c["key"]}, headers=h)
    text = pypdfium2.PdfDocument(pdf.content)[0].get_textpage().get_text_range()
    assert pdf.status_code == 200 and "Payments received" in text and "24AAAAA7777A1Z5" in text
    assert "24AAAAA8888A1Z5" not in text and "30-Sep-2026" in text
    other_pdf = client.get("/receivables/statement.pdf", params={"client": other["key"]}, headers=h)
    assert "24AAAAA8888A1Z5" in pypdfium2.PdfDocument(other_pdf.content)[0].get_textpage().get_text_range()

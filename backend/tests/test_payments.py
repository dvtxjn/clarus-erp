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

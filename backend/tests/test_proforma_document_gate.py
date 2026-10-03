import pytest

from tests.conftest import be_pdf


@pytest.mark.document_gate
def test_no_proforma_until_the_assessed_be_is_attached(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "GATE00000001"}, headers=h).json()["id"]
    r = client.post(f"/shipments/{sid}/proformas", json={}, headers=h)
    assert r.status_code == 409 and "Not attached: Assessed BE" in r.json()["detail"]
    assert client.get(f"/shipments/{sid}/proformas", headers=h).json() == []

    r = client.post(f"/shipments/{sid}/documents", data={"document_type": "assessed_bill_of_entry"},
                    files={"file": ("be.pdf", be_pdf(be_no="5559901", mawb="GATE00000001"), "application/pdf")},
                    headers=h)
    assert r.status_code == 201, r.text
    r = client.post(f"/shipments/{sid}/proformas", json={}, headers=h)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.get(f"/proformas/{pid}/invoice", headers=h).json()["not_attached"] == []
    assert client.get(f"/proformas/{pid}/invoice.pdf", headers=h).status_code == 200
    assert client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).status_code == 200

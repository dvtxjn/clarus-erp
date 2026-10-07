def test_org_checks_and_soft_delete(client, admin_headers):
    h = admin_headers
    post = lambda **kw: client.post("/organizations", json={"name": "Orgcheck Traders Private Limited", **kw}, headers=h)
    assert post(pan="ABC").status_code == 422
    assert post(gstin="24AAACO1234F1Z5", pan="AAACX1234F").status_code == 422   # PAN not in the GSTIN
    r = post(gstin="24aaaco1234f1z5", pan="aaaco1234f", iec="aaaco1234f")
    assert r.status_code == 201, r.text
    org = r.json()
    assert org["gstin"] == "24AAACO1234F1Z5" and org["iec"] == "AAACO1234F"
    dup = client.post("/organizations", json={"name": "ORGCHECK TRADERS PVT. LTD."}, headers=h)
    assert dup.status_code == 400 and "Orgcheck" in dup.json()["detail"]
    assert client.delete(f"/organizations/{org['id']}", headers=h).status_code == 204
    assert all(o["id"] != org["id"] for o in client.get("/organizations", headers=h).json())
    assert client.post(f"/deleted/organization/{org['id']}/restore", headers=h).status_code == 200
    assert any(o["id"] == org["id"] for o in client.get("/organizations", headers=h).json())


def test_manual_challan_needs_a_real_be(client, admin_headers):
    post = lambda be: client.post("/duty-challans", json={"be_no": be, "due_amount": "10"}, headers=admin_headers)
    assert post("").status_code == 422
    assert post("12AB").status_code == 422
    assert post("7777771").status_code == 422   # no shipment has it

def test_standard_rates_screen(client, admin_headers):
    h = admin_headers
    charges = {c["code"]: c for c in client.get("/charge-master", headers=h).json()}
    assert float(charges["SBOND"]["default_rate"]) == 1500 and float(charges["DC"]["default_rate"]) == 1500
    ac = charges["AC"]
    r = client.patch(f"/charge-master/{ac['id']}", json={"default_rate": "7500"}, headers=h)
    assert r.status_code == 200 and float(r.json()["default_rate"]) == 7500
    client.patch(f"/charge-master/{ac['id']}", json={"default_rate": "7000"}, headers=h)
    # automatic ones can't be given a rate
    assert client.patch(f"/charge-master/{charges['GSTD']['id']}", json={"default_rate": "1"}, headers=h).status_code == 400
    # new charge, then retire it
    new = client.post("/charge-master", json={"name": "Other Fees", "code": "OTHERFEES", "default_rate": "100000"},
                      headers=h).json()
    assert new["category"] == "service"
    client.patch(f"/charge-master/{new['id']}", json={"is_active": False}, headers=h)
    assert "OTHERFEES" not in {c["code"] for c in client.get("/charge-master", headers=h).json()}
    assert "OTHERFEES" in {c["code"] for c in client.get("/charge-master?include_inactive=true", headers=h).json()}


def test_licence_api(client, admin_headers):
    h = admin_headers
    lic = {l["number"]: l for l in client.get("/licences", headers=h).json()}
    assert lic["111021207"]["is_active"] is False and lic["111022154"]["importer_name"] == "MAHRISHI RECYCLERS"
    body = {**lic["111021955"], "rates": lic["111021955"]["rates"] + [{"code": "DC", "flat": "1200"}]}
    r = client.put(f"/licences/{body['id']}", json=body, headers=h)
    assert r.status_code == 200 and any(x["code"] == "DC" and float(x["flat"]) == 1200 for x in r.json()["rates"])
    assert client.post("/licences", json={"number": "999", "rates": [{"code": "NOPE"}]}, headers=h).status_code == 400

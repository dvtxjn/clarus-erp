from datetime import date, timedelta

from app.models.shipment import Shipment


def test_days_matches_sheet_formula():
    inw = date.today() - timedelta(days=31)
    assert Shipment(inw=inw.strftime("%d-%b-%Y")).days == "32 days"  # today - INW + 1
    assert Shipment(inw=date.today().strftime("%d-%b-%Y")).days == "1 day"
    assert Shipment(inw=(date.today() + timedelta(days=3)).strftime("%d-%b-%Y")).days == "-3 days"
    assert Shipment(inw=(date.today() + timedelta(days=1)).strftime("%d-%b-%Y")).days == "-1 day"
    assert Shipment(inw="PIPAVAV").days == "Pending"
    assert Shipment(inw=None).days == "Pending"


def test_patch_new_sheet_columns_and_ports(client, admin_headers):
    sid = client.post("/shipments", json={"mbl": "MBLNOJOB1"}, headers=admin_headers).json()["id"]
    r = client.patch(f"/shipments/{sid}", json={"shipping_line": "HMM", "igm_date": "2026-09-20", "remark": "OOC"},
                     headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert (body["job"], body["shipping_line"], body["igm_date"], body["days"]) == ("", "HMM", "2026-09-20", "Pending")
    codes = {p["code"]: p["name"] for p in client.get("/ports", headers=admin_headers).json()}
    assert codes["INMUN1"] == "Mundra"


def test_rename_client_all_rows(client, admin_headers):
    ids = [client.post("/shipments", json={"mbl": f"RN{i}", "client": "old co "}, headers=admin_headers).json()["id"]
           for i in range(2)]
    other = client.post("/shipments", json={"mbl": "RN-X", "client": "keep me"}, headers=admin_headers).json()["id"]
    r = client.post("/shipments/rename-client", json={"old_name": "old co", "new_name": "New Co"}, headers=admin_headers)
    assert r.json() == {"updated": 2}
    assert {client.get(f"/shipments/{i}", headers=admin_headers).json()["client"] for i in ids} == {"New Co"}
    assert client.get(f"/shipments/{other}", headers=admin_headers).json()["client"] == "keep me"
    assert client.post("/shipments/rename-client", json={"old_name": "New Co", "new_name": " "},
                       headers=admin_headers).status_code == 400


def test_custom_columns_lifecycle(client, admin_headers):
    col = client.post("/tracker-columns", json={"label": "Truck No", "data_type": "text"}, headers=admin_headers).json()
    assert col["key"] == "c_truck_no" and col["is_custom"]
    sid = client.post("/shipments", json={"mbl": "CUSTOM1"}, headers=admin_headers).json()["id"]
    r = client.patch(f"/shipments/{sid}", json={"custom_fields": {"c_truck_no": " MH04 AB 1234 "}}, headers=admin_headers)
    assert r.json()["custom_fields"] == {"c_truck_no": "MH04 AB 1234"}
    assert client.patch(f"/shipments/{sid}", json={"custom_fields": {"nope": 1}}, headers=admin_headers).status_code == 400
    assert client.delete("/tracker-columns/c_truck_no", headers=admin_headers).status_code == 204
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["custom_fields"] == {}


def test_remove_and_restore_builtin(client, admin_headers):
    r = client.post("/tracker-columns/remove-builtin", json={"key": "hbl", "label": "HBL"}, headers=admin_headers)
    assert r.json()["is_removed"] is True
    assert client.post("/tracker-columns/remove-builtin", json={"key": "mbl", "label": "MBL"},
                       headers=admin_headers).status_code == 400
    assert client.post("/tracker-columns/restore-builtin/hbl", headers=admin_headers).json()["is_removed"] is False


def test_bill_and_unbill_restores_status(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "BILL1", "cleared_date": "2026-09-10"}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"duty_paid": True, "cfs_inv_received": True, "line_paid": True,
                                            "ooc": True, "do": True}, headers=h)
    s = client.post(f"/shipments/{sid}/bill", headers=h).json()
    assert s["is_billed"] and s["status"] == "billed" and s["billed_at"] is not None
    s = client.post(f"/shipments/{sid}/unbill", headers=h).json()
    assert not s["is_billed"] and s["status"] == "cleared" and s["billed_at"] is None
    # billed shipments still come back in the list (they aren't hidden)
    s = client.post(f"/shipments/{sid}/bill", headers=h).json()
    ids = [x["id"] for x in client.get("/shipments?include_archived=true", headers=h).json()]
    assert sid in ids


def test_hss_detected_from_consignee_and_editable(client, admin_headers):
    h = admin_headers
    s = client.post("/shipments", json={"mbl": "HSS1", "consignee": "HKR - Mahrishi"}, headers=h).json()
    assert (s["is_hss"], s["hss_seller"], s["hss_buyer"]) == (True, "HKR", "Mahrishi")
    s = client.patch(f"/shipments/{s['id']}", json={"consignee": "Homezone"}, headers=h).json()
    assert (s["is_hss"], s["hss_seller"]) == (False, None)
    s = client.patch(f"/shipments/{s['id']}", json={"is_hss": True, "hss_seller": "A Co", "hss_buyer": "B Co"},
                     headers=h).json()
    assert (s["is_hss"], s["hss_seller"], s["hss_buyer"]) == (True, "A Co", "B Co")


def test_hss_proformas_one_per_party_and_rename(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "HSS2", "consignee": "Earthman - Mahrishi"}, headers=h).json()["id"]
    r = client.post(f"/shipments/{sid}/proformas", headers=h)
    assert r.status_code == 400 and "seller or the buyer" in r.json()["detail"]
    seller = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "seller"}, headers=h).json()
    buyer = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer", "name": "Buyer copy"},
                        headers=h).json()
    # Bill To is always the BE importer (the buyer); the role says whose copy it is
    assert (seller["bill_to"], buyer["bill_to"], buyer["name"]) == ("Mahrishi", "Mahrishi", "Buyer copy")
    assert (seller["bill_to_role"], buyer["bill_to_role"]) == ("seller", "buyer")
    renamed = client.patch(f"/proformas/{seller['id']}", json={"name": "Seller — revised"}, headers=h).json()
    assert renamed["name"] == "Seller — revised" and renamed["status"] == "draft"
    normal = client.post("/shipments", json={"mbl": "HSS3", "consignee": "Divine"}, headers=h).json()["id"]
    p = client.post(f"/shipments/{normal}/proformas", headers=h).json()
    assert p["bill_to"] == "Divine" and p["bill_to_role"] is None


def test_cleared_loads_separately(client, admin_headers):
    h = admin_headers
    done = client.post("/shipments", json={"mbl": "CLR-DONE", "cleared_date": "2026-09-10"}, headers=h).json()["id"]
    client.patch(f"/shipments/{done}", json={"duty_paid": True, "cfs_inv_received": True, "line_paid": True,
                                             "ooc": True, "do": True}, headers=h)
    gap = client.post("/shipments", json={"mbl": "CLR-GAP", "cleared_date": "2026-09-10"}, headers=h).json()["id"]
    live = client.post("/shipments", json={"mbl": "CLR-LIVE"}, headers=h).json()["id"]
    ongoing = {x["id"] for x in client.get("/shipments?include_archived=true&cleared=false", headers=h).json()}
    cleared = {x["id"] for x in client.get("/shipments?include_archived=true&cleared=true", headers=h).json()}
    assert {gap, live} <= ongoing and done not in ongoing  # a Cleared Date with a check missing stays Ongoing
    assert done in cleared and not {gap, live} & cleared
    assert client.get("/shipments/cleared-count", headers=h).json()["count"] == len(cleared)

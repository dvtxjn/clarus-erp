def _patch(client, h, sid, **kw):
    r = client.patch(f"/shipments/{sid}", json=kw, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["status"]


def test_status_follows_evidence(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "RULES1"}, headers=h).json()["id"]
    assert _patch(client, h, sid, remarks="x") == "to_be_filed"  # not evidence
    assert _patch(client, h, sid, igm="1212400") == "igm_filed"
    assert _patch(client, h, sid, be_no="4041785") == "be_filed"
    assert _patch(client, h, sid, duty_amount="61500") == "be_assessed"
    assert _patch(client, h, sid, duty_paid=True) == "duty_paid"
    assert _patch(client, h, sid, ooc=True) == "ooc_done"
    # Cleared needs the Cleared Date AND all five checks (Duty, CFS Inv, Line, OOC, DO)
    assert _patch(client, h, sid, cleared_date="2026-09-20") == "ooc_done"
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["is_fully_cleared"] is False and s["missing_for_clearance"] == ["CFS Inv", "Line", "DO"]
    assert _patch(client, h, sid, cfs_inv_received=True, line_paid=True) == "ooc_done"
    assert _patch(client, h, sid, do=True) == "cleared"
    assert client.get(f"/shipments/{sid}", headers=h).json()["is_fully_cleared"] is True
    # unticking any of them (or removing the date) moves it back
    assert _patch(client, h, sid, line_paid=False) == "ooc_done"
    assert _patch(client, h, sid, line_paid=True) == "cleared"
    assert _patch(client, h, sid, cleared_date=None) == "ooc_done"
    assert _patch(client, h, sid, ooc=False) == "duty_paid"


def test_jumps_forward_and_manual_status_wins(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "RULES2"}, headers=h).json()["id"]
    assert _patch(client, h, sid, ooc=True) == "ooc_done"  # evidence can skip steps
    # a status typed by hand in the same edit is kept
    assert _patch(client, h, sid, be_no="1000001", status="under_ooc") == "under_ooc"
    # Under OOC has no evidence rule, so unrelated evidence changes don't pull it back
    assert _patch(client, h, sid, igm="99") == "ooc_done"  # ...but more evidence can still move it forward


def test_new_shipment_gets_status_from_its_evidence(client, admin_headers):
    s = client.post("/shipments", json={"mbl": "RULES3", "igm": "1", "be_no": "2000002"}, headers=admin_headers).json()
    assert s["status"] == "be_filed"


def test_billed_is_left_alone(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "RULES4", "cleared_date": "2026-09-10"}, headers=h).json()["id"]
    assert client.post(f"/shipments/{sid}/bill", headers=h).status_code == 200
    assert _patch(client, h, sid, igm="5") == "billed"

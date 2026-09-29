"""Launch Phase 2: PATCH with `base` never silently overwrites someone else's change."""


def _ship(client, h, mbl, **kw):
    r = client.post("/shipments", json={"mbl": mbl, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _patch(client, h, sid, base, **changes):
    return client.patch(f"/shipments/{sid}", json={**changes, "base": base}, headers=h)


def test_same_field_second_editor_gets_409(client, admin_headers):
    h = admin_headers
    s = _ship(client, h, "CONF0000001", remarks="old")
    assert s["version"] == 1
    a = _patch(client, h, s["id"], {"remarks": "old"}, remarks="from A")
    assert a.status_code == 200 and a.json()["version"] == 2
    b = _patch(client, h, s["id"], {"remarks": "old"}, remarks="from B")  # B still saw "old"
    assert b.status_code == 409
    d = b.json()["detail"]
    c = d["conflicts"][0]
    assert (c["field"], c["current"], c["yours"]) == ("remarks", "from A", "from B")
    assert c["changed_by"] and c["changed_at"]
    assert d["version"] == 2 and d["shipment"]["remarks"] == "from A"
    assert client.get(f"/shipments/{s['id']}", headers=h).json()["remarks"] == "from A"  # nothing changed
    # "Keep mine": re-send with the fresh base
    k = _patch(client, h, s["id"], {"remarks": "from A"}, remarks="from B")
    assert k.status_code == 200 and k.json()["remarks"] == "from B" and k.json()["version"] == 3


def test_different_fields_do_not_conflict(client, admin_headers):
    h = admin_headers
    s = _ship(client, h, "CONF0000002")
    assert _patch(client, h, s["id"], {"remarks": None}, remarks="A's note").status_code == 200
    r = _patch(client, h, s["id"], {"poc": None}, poc="B")
    assert r.status_code == 200 and r.json()["remarks"] == "A's note" and r.json()["poc"] == "B"


def test_same_new_value_is_not_a_conflict_and_numbers_compare_as_numbers(client, admin_headers):
    h = admin_headers
    s = _ship(client, h, "CONF0000003")
    client.patch(f"/shipments/{s['id']}", json={"duty_amount": "1500"}, headers=h)
    # someone already typed the same thing
    assert _patch(client, h, s["id"], {"duty_amount": None}, duty_amount="1500.00").status_code == 200
    # 1500 == "1500.00"
    assert _patch(client, h, s["id"], {"duty_amount": 1500}, duty_amount="1600").status_code == 200


def test_custom_column_conflict(client, admin_headers):
    h = admin_headers
    client.post("/tracker-columns", json={"label": "Gate Pass Ref", "data_type": "text"}, headers=h)
    key = next(c["key"] for c in client.get("/tracker-columns", headers=h).json() if c["label"] == "Gate Pass Ref")
    s = _ship(client, h, "CONF0000004")
    base = {"custom_fields": {key: None}}
    assert _patch(client, h, s["id"], base, custom_fields={key: "MH04 1111"}).status_code == 200
    r = _patch(client, h, s["id"], base, custom_fields={key: "MH04 2222"})
    assert r.status_code == 409 and r.json()["detail"]["conflicts"][0]["current"] == "MH04 1111"


def test_status_rules_still_fire_with_base(client, admin_headers):
    h = admin_headers
    s = _ship(client, h, "CONF0000005")
    r = _patch(client, h, s["id"], {"igm": None}, igm="2345678")
    assert r.status_code == 200 and r.json()["status"] == "igm_filed"


def test_without_base_old_behaviour(client, admin_headers):
    h = admin_headers
    s = _ship(client, h, "CONF0000006", remarks="x")
    client.patch(f"/shipments/{s['id']}", json={"remarks": "y"}, headers=h)
    assert client.patch(f"/shipments/{s['id']}", json={"remarks": "z"}, headers=h).status_code == 200

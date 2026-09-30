"""Change history: a shipment's changes (who / when / was → now), putting a field back, and the admin's log."""


def test_shipment_history_and_put_back(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "HIST0001", "job": "8801", "client": "Hist Co"}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"remarks": "first"}, headers=h)
    client.patch(f"/shipments/{sid}", json={"remarks": "second", "duty_paid": True, "eta": "2026-10-05"}, headers=h)
    client.post(f"/shipments/{sid}/containers", json={"container_no": "HIST1234567"}, headers=h)

    rows = client.get(f"/shipments/{sid}/history", headers=h).json()
    remarks = [r for r in rows if r["field"] == "remarks"]
    assert [(r["old"], r["new"]) for r in remarks] == [("first", "second"), (None, "first")]  # newest first
    assert remarks[0]["who"] and not remarks[0]["automatic"]
    assert remarks[0]["undo"] == {"remarks": "first"} and remarks[1]["undo"] is None  # only the newest change
    assert any(r["kind"] == "Container" and r["about"] == "HIST1234567" for r in rows)
    duty = next(r for r in rows if r["field"] == "duty_paid")
    assert duty["undo"] == {"duty_paid": False}
    eta = next(r for r in rows if r["field"] == "eta")
    assert eta["undo"] == {"eta": None}

    # put back = the normal edit; recorded too
    assert client.patch(f"/shipments/{sid}", json=duty["undo"], headers=h).json()["duty_paid"] is False
    rows = client.get(f"/shipments/{sid}/history", headers=h).json()
    assert [r["new"] for r in rows if r["field"] == "duty_paid"][:1] == ["False"]

    # changed again since -> that older entry can't be put back
    client.patch(f"/shipments/{sid}", json={"remarks": "third"}, headers=h)
    rows = client.get(f"/shipments/{sid}/history", headers=h).json()
    assert [r["undo"] for r in rows if r["field"] == "remarks" and r["new"] == "second"] == [None]


def test_admin_log_filters(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "HISTLOG01", "job": "8802"}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"remarks": "log me"}, headers=h)
    rows = client.get("/history?q=HISTLOG01", headers=h).json()
    assert rows and all(r.get("job") == "8802" for r in rows if r["table"] == "shipments")
    assert any(r["field"] == "remarks" and r["new"] == "log me" for r in rows)
    assert not client.get("/history?q=HISTLOG01&who=auto", headers=h).json() or \
        all(r["automatic"] for r in client.get("/history?q=HISTLOG01&who=auto", headers=h).json())
    f = client.get("/history/filters", headers=h).json()
    assert any(k["kind"] == "shipments" and k["label"] == "Shipment" for k in f["kinds"]) and f["users"]

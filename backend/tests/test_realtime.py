"""Live updates: a committed shipment change is broadcast (with who made it); a rolled-back
one is not. Postgres goes through NOTIFY/LISTEN, SQLite through the in-process hub."""
import time

import pytest

from app.core import realtime
from app.core.database import SessionLocal
from app.models.shipment import Shipment


@pytest.fixture
def heard(monkeypatch, client):
    got = []
    monkeypatch.setattr(realtime.hub, "publish", lambda msg: got.append(msg))
    return got


def _wait_for(got, pred, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if any(pred(m) for m in got):
            return True
        time.sleep(0.05)
    return False


def test_committed_edit_is_broadcast_with_author(client, admin_headers, heard):
    sid = client.post("/shipments", json={"mbl": "LIVE0000001"}, headers=admin_headers).json()["id"]
    client.patch(f"/shipments/{sid}", json={"poc": "live"}, headers=admin_headers)
    assert _wait_for(heard, lambda m: m.get("t") == "s" and m["id"] == sid and m["v"] == 2 and m["by"] == "Admin")


def test_rolled_back_change_is_not_broadcast(client, admin_headers, heard):
    sid = client.post("/shipments", json={"mbl": "LIVE0000002"}, headers=admin_headers).json()["id"]
    time.sleep(0.3)
    heard.clear()
    with SessionLocal() as db:
        s = db.get(Shipment, sid)
        s.poc = "never saved"
        db.flush()
        db.rollback()
    assert not _wait_for(heard, lambda m: m.get("id") == sid, seconds=1.0)
    with SessionLocal() as db:
        db.get(Shipment, sid).poc = "saved"
        db.commit()
    assert _wait_for(heard, lambda m: m.get("id") == sid)


def test_conflict_409_broadcasts_nothing(client, admin_headers, heard):
    sid = client.post("/shipments", json={"mbl": "LIVE0000003", "poc": "a"}, headers=admin_headers).json()["id"]
    time.sleep(0.3)
    heard.clear()
    r = client.patch(f"/shipments/{sid}", json={"poc": "b", "base": {"poc": "old"}}, headers=admin_headers)
    assert r.status_code == 409
    assert not _wait_for(heard, lambda m: m.get("id") == sid, seconds=1.0)


def test_presence_and_stream_auth(client, admin_headers, heard):
    sid = client.post("/shipments", json={"mbl": "LIVE0000004", "port": "INNSA1"}, headers=admin_headers).json()["id"]
    assert client.post("/realtime/presence", json={"shipment_id": sid, "field": "poc"},
                       headers=admin_headers).status_code == 204
    assert _wait_for(heard, lambda m: m.get("t") == "p" and m["sid"] == sid and m["f"] == "poc" and m["port"] == "INNSA1")
    assert client.get("/realtime/stream").status_code == 401


def test_port_scoped_streams_only_get_their_ports():
    sub = realtime.Subscriber(user_id=9, ports=["INMUN1"])
    assert sub.wants({"t": "s", "port": "INMUN1"}) and not sub.wants({"t": "s", "port": "INNSA1"})
    assert sub.wants({"t": "resync"})
    assert realtime.Subscriber(user_id=9, ports=None).wants({"t": "s", "port": "INNSA1"})

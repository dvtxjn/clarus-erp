"""Which shipments the 6-hourly ICEGATE read takes."""
from datetime import date, timedelta

from app.core.database import SessionLocal
from app.igm import batch


def make(client, h, **kw):
    r = client.post("/shipments", json=kw, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_due_rules(client, admin_headers):
    today = date.today()
    soon, later, past = (today + timedelta(days=2)).isoformat(), (today + timedelta(days=10)).isoformat(), (today - timedelta(days=3)).isoformat()
    sea_due = make(client, admin_headers, mbl="DUE-SEA-1", port="INMUN1", eta=soon)
    sea_in = make(client, admin_headers, mbl="DUE-SEA-2", port="INMUN1", eta=past, inw="01-Sep-2026")
    client.post(f"/shipments/{sea_in}/containers", json={"container_no": "SEAI1234567"}, headers=admin_headers)
    sea_nobox = make(client, admin_headers, mbl="DUE-SEA-4", port="INNSA1", eta=past, inw="01-Sep-2026")  # inward, no containers yet
    sea_far = make(client, admin_headers, mbl="DUE-SEA-3", port="INNSA1", eta=later)
    icd_new = make(client, admin_headers, mbl="DUE-ICD-1", port="INDWN6", eta=past)
    icd_done = make(client, admin_headers, mbl="DUE-ICD-2", port="INDWN6", eta=past)
    client.post(f"/shipments/{icd_done}/containers", json={"container_no": "DONE1234567", "arrival_date": past}, headers=admin_headers)
    icd_half = make(client, admin_headers, mbl="DUE-ICD-3", port="INDWN6", eta=past)
    client.post(f"/shipments/{icd_half}/containers", json={"container_no": "HALF1234567", "arrival_date": past}, headers=admin_headers)
    client.post(f"/shipments/{icd_half}/containers", json={"container_no": "HALF7654321"}, headers=admin_headers)

    db = SessionLocal()
    try:
        ids = {s.id for s in batch.due(db)}
    finally:
        db.close()
    assert sea_due in ids and sea_nobox in ids and icd_new in ids and icd_half in ids
    assert sea_in not in ids and sea_far not in ids and icd_done not in ids


def test_failure_recorded_and_retried(client, admin_headers, monkeypatch):
    import httpx
    from app.igm import refresh
    from app.models.shipment import Shipment

    sid = client.post("/shipments", json={"mbl": "FAILRETRY1", "job": "8901"}, headers=admin_headers).json()["id"]
    calls = []

    def boom(db, s, _):
        calls.append(1)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(refresh, "refresh", boom)
    monkeypatch.setattr(batch, "PAUSE_SECONDS", 0)
    db = SessionLocal()
    s = db.get(Shipment, sid)
    s.icegate = {"fetched_at": "2026-09-29T08:00", "sea_found": True}
    db.commit()
    try:
        batch._refresh_with_retry(db, s)
    except httpx.HTTPError as e:
        batch.record_failure(db, s, e)
    assert len(calls) == 2
    db.refresh(s)
    assert s.icegate["error"] == "ICEGATE didn't answer" and s.icegate["sea_found"]  # last good read kept
    db.close()

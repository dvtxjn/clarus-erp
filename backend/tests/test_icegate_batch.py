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
    assert sea_due in ids and icd_new in ids and icd_half in ids
    assert sea_in not in ids and sea_far not in ids and icd_done not in ids

"""The tracker's search finds a shipment by its container number (full or part)."""
from app.core.database import SessionLocal
from app.models.container import ShipmentContainer


def test_list_carries_container_numbers_and_search_matches_them(client, admin_headers):
    sid = client.post("/shipments", json={"mbl": "CNTRSEARCH01"}, headers=admin_headers).json()["id"]
    with SessionLocal() as db:
        db.add(ShipmentContainer(shipment_id=sid, container_no="CAAU7596246"))
        db.commit()
    rows = client.get("/shipments", headers=admin_headers).json()
    row = next(r for r in rows if r["id"] == sid)
    assert row["container_nos"] == ["CAAU7596246"]
    found = client.get("/shipments", params={"search": "AAU7596"}, headers=admin_headers).json()
    assert [r["id"] for r in found] == [sid]
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["container_nos"] == ["CAAU7596246"]


def test_newer_be_acceptance_hides_older_rejection_and_duplicates_show_once(client, admin_headers):
    from datetime import datetime, timedelta, timezone
    from app.models.icegate_mail import IcegateMail

    sid = client.post("/shipments", json={"mbl": "ALERTACK01", "job": "9188"}, headers=admin_headers).json()["id"]
    t = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with SessionLocal() as db:
        def mail(fp, kind, at, attention=False, summary="x"):
            db.add(IcegateMail(fingerprint=fp, kind=kind, label=kind, summary=summary, received_at=at,
                               shipment_id=sid, attention=attention, applied=True))
        mail("a1", "be_nak", t, True, "791_ITEMS")
        mail("a2", "be_query", t, True, "query 1")
        mail("a3", "be_query", t + timedelta(hours=1), True, "query 1")  # the same query mailed again
        mail("a4", "be_ack", t + timedelta(days=1))
        db.commit()
    got = [a for a in client.get("/shipments/alerts", headers=admin_headers).json()
           if a["shipment_id"] == sid and a["kind"] == "icegate"]
    assert [a["text"] for a in got] == ["be_query: query 1"]


def test_history_field_names_read_like_the_office():
    from app.routers.history import _label

    assert [_label(f, {}) for f in ("be_dt", "igst_amount", "ooc_done", "remarks", "mbl_date", "igm_no")] == [
        "BE date", "IGST", "OOC done", "Notes", "MBL date", "IGM no"]

"""DO -> each container's validity (client, 2026-10-05). Text shaped like a Maersk transport order / DO."""
from datetime import date

from app import alerts
from app.core.enums import DocumentType
from app.extraction.do_pdf import scan_do_text
from app.extraction.tracker_sync import apply_do_validity
from app.core.database import SessionLocal
from app.models.shipment import Shipment

CARRIER = """TRANSPORT ORDER AMENDMENT
Equipment count: 3
AAAU1111111 40 DRY 9'6 3720.000 KGS 28003.797 KGS 1
BBBU2222222 40 DRY 9'6 3720.000 KGS 25459.826 KGS 1
CCCU3333333 40 DRY 9'6 3720.000 KGS 25999.826 KGS 1
Carrier Haulage Delivery Itinerary
Type Name Cntr return Validity Time Est. Del. Date & Time Reference
Full Delivery Pickup Continental Warehousing
Panipat, 06, 06
Cargo Delivery SOME CLIENT 2026-10-07 23:59 DO valid till 07-10-2026
HAPUR, UP
AAAU1111111
BBBU2222222
Cargo Delivery SOME CLIENT 2026-10-10 23:59 DO valid till 10-10-2026
CCCU3333333
Empty Container Depot Continental Warehousing 2026-10-07 23:59
Panipat, 06, 06
"""

MERCHANT = """DELIVERY ORDER AMENDMENT
Equipment count: 1
DDDU4444444 40 DRY 9'6 3750.000 KGS 28350.000 KGS 1
Merchant Haulage Delivery Itinerary
Type Name Cntr return Validity Time Est. Del. Date & Time Reference
Full Delivery Pickup Mundra International 2026-09-15 23:59
Empty Container Depot Landmark Empty Depot
Detention Free days: 4
"""


def test_reads_each_containers_date():
    r = scan_do_text(CARRIER)
    assert r["containers"] == {"AAAU1111111": "2026-10-07", "BBBU2222222": "2026-10-07", "CCCU3333333": "2026-10-10"}
    assert r["valid_until"] == "2026-10-07"
    # merchant haulage: the pickup validity covers the container (listed only in the equipment list)
    assert scan_do_text(MERCHANT)["containers"] == {"DDDU4444444": "2026-09-15"}
    assert scan_do_text("some other letter AAAU1111111")["containers"] == {}


def test_do_sets_free_until_and_hand_typing_wins(client, admin_headers):
    db_session = SessionLocal()
    sid = client.post("/shipments", json={"mbl": "DOTEST0001", "port": "INDWN6", "job": "T-DO"}, headers=admin_headers).json()["id"]
    base = f"/shipments/{sid}/containers"
    a = client.post(base, json={"container_no": "AAAU1111111", "arrival_date": "2026-09-21"}, headers=admin_headers).json()
    assert a["last_free_day"] == "2026-10-04" and a["do_valid_until"] is None

    s = db_session.get(Shipment, sid)
    notes = apply_do_validity(db_session, s, scan_do_text(CARRIER)["containers"], None)
    db_session.commit()
    assert "2 containers till 07 Oct 2026" in notes[0] and "added" in notes[1]
    rows = {c["container_no"]: c for c in client.get(base, headers=admin_headers).json()}
    assert set(rows) == {"AAAU1111111", "BBBU2222222", "CCCU3333333"}
    assert rows["AAAU1111111"]["last_free_day"] == "2026-10-07" and rows["AAAU1111111"]["do_valid_until"] == "2026-10-07"
    assert rows["CCCU3333333"]["last_free_day"] == "2026-10-10" and rows["CCCU3333333"]["source"] == "do"

    # revalidated DO: the newer date replaces it
    apply_do_validity(db_session, s, {"AAAU1111111": "2026-10-15"}, None)
    db_session.commit()
    assert client.get(base, headers=admin_headers).json()[0]["last_free_day"] == "2026-10-15"

    # typing days free by hand wins over the DO; clear_do counts from the arrival again
    r = client.patch(f"{base}/{a['id']}", json={"free_days": 20}, headers=admin_headers).json()
    assert r["do_valid_until"] is None and r["last_free_day"] == "2026-10-10"
    c = rows["CCCU3333333"]
    r = client.patch(f"{base}/{c['id']}", json={"clear_do": True}, headers=admin_headers).json()
    assert r["do_valid_until"] is None and r["last_free_day"] is None  # no arrival yet
    db_session.close()


def test_alert_uses_the_do_date():
    s = Shipment(job="1", mbl="X", port="INDWN6")
    # arrived 25 Sep (standard: free till 08 Oct) but the DO says 01 Oct -> 1 day left on 30 Sep
    a = alerts.fpod_alert(s, [("A", date(2026, 9, 25), None, date(2026, 10, 1))], date(2026, 9, 30))
    assert a and a["days_left"] == 1
    assert DocumentType.DO_LETTER

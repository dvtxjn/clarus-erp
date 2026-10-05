"""Inland shipments: containers + arrival at the FPOD from ICEGATE's ICD BL status (faked here, no network)."""
from datetime import date

import httpx
import pytest

from app.igm import icd

BL = [{"igmRTN": "4372925", "igmDT": "03 SEP 2026", "lineNo": "211", "subLineNo": "0", "mawbNo": "274014260",
       "portDest": "INDWN6", "portREP": "INMUN1", "fileName": "INDWN6", "inwDT": "03 SEP 2026", "smtpNo": "2724782",
       "smtpDT": "03 SEP 2026", "totalPackage": "253", "packageCode": "PKG", "grossWeight": "269699", "uqc": "KGS"}]
CONT = [
    {"contNo": "MRKU5032093", "contStatus": "FCL", "arrDT": "21 SEP 2026", "arrStatus": "I", "errCode": "40|41"},
    {"contNo": "MRSU4711430", "contStatus": "FCL", "arrDT": "21 SEP 2026", "arrStatus": "I", "errCode": "00"},
    {"contNo": "MRKU5032093", "contStatus": "FCL", "arrDT": "21 SEP 2026", "arrStatus": "I", "errCode": "00"},
    {"contNo": "TCNU4951934", "contStatus": "FCL", "arrDT": "N.A.", "arrStatus": "N.A.", "errCode": "00"},
]


def fake_icegate(bl=BL, cont=CONT):
    def handler(req: httpx.Request):
        if req.url.path.endswith("publicblstatus-action"):
            return httpx.Response(200, json=bl)
        return httpx.Response(200, json=cont)
    return httpx.Client(transport=httpx.MockTransport(handler), headers=icd.HEADERS)


def test_parse_and_merge_duplicates():
    d = icd.fetch("274014260", client=fake_icegate())
    assert d["found"] and d["bls"][0]["smtp_no"] == "2724782" and d["bls"][0]["inward_date"] == date(2026, 9, 3)
    got = {c["container_no"]: c["arrival_date"] for c in d["containers"]}
    assert got == {"MRKU5032093": date(2026, 9, 21), "MRSU4711430": date(2026, 9, 21), "TCNU4951934": None}


def test_not_found():
    assert icd.fetch("X", client=fake_icegate(bl=[])) == {"found": False}


@pytest.fixture
def inland(client, admin_headers):
    r = client.post("/shipments", json={"mbl": "ICDTEST0001", "port": "INDWN6", "job": "T-ICD"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_refresh_keeps_hand_typed_dates(client, admin_headers, inland, monkeypatch):
    real_fetch = icd.fetch
    monkeypatch.setattr(icd, "fetch", lambda mbl: real_fetch(mbl, client=fake_icegate()))
    base = f"/shipments/{inland}/containers"

    r = client.post(f"{base}/refresh-icd", headers=admin_headers)
    assert r.status_code == 200 and r.json()["added"] == 3
    rows = {c["container_no"]: c for c in r.json()["containers"]}
    # standard 14 free days at the ICD — arrival 21 Sep is day 1, last free day 04 Oct
    assert rows["MRKU5032093"]["free_days"] == 14 and rows["MRKU5032093"]["last_free_day"] == "2026-10-04"

    # someone types a different arrival for one container
    cid = rows["MRSU4711430"]["id"]
    r = client.patch(f"{base}/{cid}", json={"arrival_date": "2026-09-23"}, headers=admin_headers)
    assert r.json()["is_manual"] and r.json()["last_free_day"] == "2026-10-06"

    # fetching again leaves the typed date alone and adds nothing twice
    r = client.post(f"{base}/refresh-icd", headers=admin_headers).json()
    assert r["added"] == 0 and r["kept_manual"] == 1
    assert {c["container_no"]: c["arrival_date"] for c in r["containers"]}["MRSU4711430"] == "2026-09-23"


def test_add_and_remove_by_hand(client, admin_headers, inland):
    base = f"/shipments/{inland}/containers"
    r = client.post(base, json={"container_no": "abcu 1234567", "arrival_date": "2026-09-25"}, headers=admin_headers)
    assert r.status_code == 201 and r.json()["container_no"] == "ABCU1234567"
    assert client.post(base, json={"container_no": "ABCU1234567"}, headers=admin_headers).status_code == 409
    assert client.delete(f"{base}/{r.json()['id']}", headers=admin_headers).status_code == 204
    assert client.get(base, headers=admin_headers).json() == []
    # the removal is in the shipment's history, and Recently deleted can bring it back
    hist = client.get(f"/shipments/{inland}/history", headers=admin_headers).json()
    assert any(e["field"] == "deleted" and e["about"] == "ABCU1234567" for e in hist)
    gone = [d for d in client.get("/deleted", headers=admin_headers).json() if d["kind"] == "container"]
    assert gone and gone[0]["label"] == "Container ABCU1234567" and gone[0]["shipment_id"] == inland
    assert client.post(f"/deleted/container/{r.json()['id']}/restore", headers=admin_headers).status_code == 200
    assert [c["container_no"] for c in client.get(base, headers=admin_headers).json()] == ["ABCU1234567"]
    # removed again and typed in again by hand: restoring the old one would make a duplicate — refused
    client.delete(f"{base}/{r.json()['id']}", headers=admin_headers)
    client.post(base, json={"container_no": "ABCU1234567"}, headers=admin_headers)
    assert client.post(f"/deleted/container/{r.json()['id']}/restore", headers=admin_headers).status_code == 400


def test_days_free_and_free_until_per_container(client, admin_headers, inland):
    base = f"/shipments/{inland}/containers"
    c = client.post(base, json={"container_no": "FREE1234567", "arrival_date": "2026-09-21"}, headers=admin_headers).json()
    assert c["free_days"] == 14 and not c["free_days_typed"] and c["last_free_day"] == "2026-10-04"
    r = client.patch(f"{base}/{c['id']}", json={"free_days": 30}, headers=admin_headers).json()
    assert r["free_days_typed"] and r["last_free_day"] == "2026-10-20"
    # typing the date instead stores it as days from the arrival
    r = client.patch(f"{base}/{c['id']}", json={"free_until": "2026-10-06"}, headers=admin_headers).json()
    assert r["free_days"] == 16 and r["last_free_day"] == "2026-10-06"
    r = client.patch(f"{base}/{c['id']}", json={"clear_free_days": True}, headers=admin_headers).json()
    assert r["free_days"] == 14 and not r["free_days_typed"]
    # no arrival yet: days free can still be set, a date can't
    n = client.post(base, json={"container_no": "NOAR1234567"}, headers=admin_headers).json()
    assert client.patch(f"{base}/{n['id']}", json={"free_days": 21}, headers=admin_headers).json()["free_days"] == 21
    assert client.patch(f"{base}/{n['id']}", json={"free_until": "2026-10-06"}, headers=admin_headers).status_code == 400


def test_tracking_status_is_typed(client, admin_headers, inland):
    base = f"/shipments/{inland}/containers"
    c = client.post(base, json={"container_no": "RAIL1234567"}, headers=admin_headers).json()
    r = client.patch(f"{base}/{c['id']}", json={"tracking_status": "  On rail  "}, headers=admin_headers).json()
    assert r["tracking_status"] == "On rail"
    assert client.patch(f"{base}/{c['id']}", json={"tracking_status": ""}, headers=admin_headers).json()["tracking_status"] is None


def test_empty_reply_means_not_found():
    # ICEGATE answers an unknown MBL with an empty body, not []
    empty = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"")), headers=icd.HEADERS)
    assert icd.fetch("BHMA48789200", client=empty) == {"found": False}
    from app.igm import sea
    assert sea.fetch("BHMA48789200", "INMUN1", client=empty) == {"status": "IGM Not Filed"}


def test_other_icds_default_to_14(client, admin_headers):
    sid = client.post("/shipments", json={"mbl": "ICDGARHI01", "port": "INGHR6"}, headers=admin_headers).json()["id"]
    c = client.post(f"/shipments/{sid}/containers", json={"container_no": "GARH1234567", "arrival_date": "2026-09-21"},
                    headers=admin_headers).json()
    assert c["free_days"] == 14 and c["last_free_day"] == "2026-10-04"


def test_sea_port_containers_from_the_igm_free_days_from_inw(client, admin_headers, monkeypatch):
    """Sea ports too (client): the container list comes from the sea IGM; free days from the INW."""
    from app.igm import sea

    igm = {"status": "IGM Filed", "igm_no": "2345678", "igm_date": "10-Sep-2026", "inw_date": "12-Sep-2026",
           "containers": [{"container": "MSKU1234567", "status": "FCL"}, {"container": "TGHU7654321", "status": "FCL"},
                          {"container": "N.A.", "status": None}]}
    monkeypatch.setattr(sea, "fetch", lambda mbl, port: igm)
    sid = client.post("/shipments", json={"mbl": "SEACONT0001", "port": "INNSA1"}, headers=admin_headers).json()["id"]
    r = client.post(f"/shipments/{sid}/icegate/refresh", headers=admin_headers)
    assert r.status_code == 200 and r.json()["summary"]["containers"]["added"] == 2
    rows = {c["container_no"]: c for c in client.get(f"/shipments/{sid}/containers", headers=admin_headers).json()}
    assert set(rows) == {"MSKU1234567", "TGHU7654321"}
    c = rows["MSKU1234567"]
    # INW 12 Sep = day 1, 14 free days -> last free day 25 Sep; not stored, follows the INW
    assert c["arrival_from_inw"] and c["arrival_date"] == "2026-09-12" and c["last_free_day"] == "2026-09-25"
    # a second read adds nothing
    assert client.post(f"/shipments/{sid}/icegate/refresh", headers=admin_headers).json()["summary"]["containers"]["added"] == 0


def test_inland_list_from_sea_igm_arrivals_from_icd(client, admin_headers, inland, monkeypatch):
    from app.igm import sea

    real_fetch = icd.fetch
    monkeypatch.setattr(icd, "fetch", lambda mbl: real_fetch(mbl, client=fake_icegate()))
    # the IGM knows one container the ICD hasn't reported yet
    monkeypatch.setattr(sea, "fetch", lambda mbl, port: {"status": "IGM Filed", "igm_no": "1", "containers": [
        {"container": "MRKU5032093", "status": "FCL"}, {"container": "ABCU1111111", "status": "FCL"}]})
    r = client.post(f"/shipments/{inland}/icegate/refresh", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = {c["container_no"]: c for c in client.get(f"/shipments/{inland}/containers", headers=admin_headers).json()}
    assert set(rows) == {"MRKU5032093", "MRSU4711430", "TCNU4951934", "ABCU1111111"}
    assert rows["MRKU5032093"]["arrival_date"] == "2026-09-21" and not rows["MRKU5032093"]["arrival_from_inw"]
    assert rows["ABCU1111111"]["arrival_date"] is None  # inland: no INW stand-in
